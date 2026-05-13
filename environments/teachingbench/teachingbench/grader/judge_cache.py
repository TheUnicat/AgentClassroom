"""Per-row judgment cache.

A `results.jsonl` row can carry a `judge_cache` blob alongside its
`judge_breakdown*` keys:

    row["judge_cache"] = {
        "<criterion_id>": {
            "<judge_model>": [
                {"value": float | None,
                 "rationale": str,
                 "source": str,
                 "ts": float,
                 "turn": int | None},   # None = outcome-level, int = per-turn (0-indexed teacher turn)
                ...
            ]
        }
    }

This is the **single centralized record** for all judging on a rollout.
LLM judge calls and per-turn deterministic state values both land here.
The `turn` field distinguishes:
  - `turn=None`: outcome-level value (whole-rollout aggregate). What
    v1_llm_only, v2_hybrid, and the outcome path of state_v1 emit.
  - `turn=k`:    per-turn state value at the k-th teacher turn
    (0-indexed). What state_v1 emits for each per-turn-natural
    deterministic function.

Deterministic results use `model="deterministic"`. LLM results use the
actual model id (e.g. `claude-opus-4-7`).

Reading:
- `lookup_cached(row, crit, model, turn=None)` — aggregated result over
  entries matching (crit, model, turn). Numeric values averaged; most-
  recent rationale carried. None if no matching entries.
- `lookup_legacy(row, crit)` — fallback for OUTCOME-level scans: looks
  at `judge_breakdown` and `judge_breakdown__*` for v1's batched
  scores. Outcome-only (turn=None).

Writing:
- `store(row, crit, model, result, source, turn=None)` — append. Source
  is a short label like `composer:v2_hybrid` or `composer:state_v1`.

Multiple entries with the same (crit, model, turn) are averaged on
read — re-judging adds rather than overwrites, so subsequent reads
benefit from noise reduction.

Backwards compatibility: cache entries written before `turn` was
introduced have no `turn` key, which is treated as `turn=None`
(outcome-level). No migration needed.
"""

from __future__ import annotations

import time
from typing import Any

CACHE_KEY = "judge_cache"


# --- raw cache access ------------------------------------------------------


def _entries(row: dict, criterion: str, model: str, turn: int | None = None) -> list[dict]:
    """All entries matching (criterion, model, turn). `turn=None` matches
    only outcome-level entries (entries without a `turn` key OR with
    `turn` explicitly None). `turn=k` matches only entries with `turn==k`.
    """
    raw = (
        row.get(CACHE_KEY, {})
        .get(criterion, {})
        .get(model, [])
    )
    if turn is None:
        return [e for e in raw if e.get("turn") is None]
    return [e for e in raw if e.get("turn") == turn]


def lookup_cached(row: dict, criterion: str, model: str, turn: int | None = None) -> dict | None:
    """Aggregated result for (criterion, model, turn), or None.

    `turn=None` (default) returns the outcome-level cached value.
    `turn=k` returns the cached per-turn value at teacher turn k.
    """
    entries = _entries(row, criterion, model, turn)
    if not entries:
        return None
    return _aggregate(entries)


def lookup_legacy(row: dict, criterion: str) -> dict | None:
    """Scan `judge_breakdown` + any `judge_breakdown__*` for a per-criterion
    score. Returns the first match found, model-agnostic. None otherwise.
    """
    jb = row.get("judge_breakdown")
    if isinstance(jb, dict):
        v = (jb.get("scores") or {}).get(criterion)
        if v is not None:
            return {
                "value": float(v),
                "rationale": str(jb.get("rationale") or ""),
                "source": "judge_breakdown",
            }
    for k, jb in row.items():
        if not k.startswith("judge_breakdown__") or not isinstance(jb, dict):
            continue
        scores = jb.get("scores") or {}
        v = scores.get(criterion)
        if v is not None:
            return {
                "value": float(v),
                "rationale": str(jb.get("rationale") or ""),
                "source": k,
            }
    return None


def store(
    row: dict,
    criterion: str,
    model: str,
    result: dict,
    source: str,
    *,
    turn: int | None = None,
) -> None:
    """Append a new entry to the cache for (criterion, model, turn).

    `turn=None` writes an outcome-level entry (the default, used by
    the LLM caching path). `turn=k` writes a per-turn state value.
    """
    cache = row.setdefault(CACHE_KEY, {})
    by_crit = cache.setdefault(criterion, {})
    entries = by_crit.setdefault(model, [])
    entries.append({
        "value": result.get("value"),
        "rationale": str(result.get("rationale") or ""),
        "source": source,
        "ts": time.time(),
        "turn": turn,
    })


def store_many(
    row: dict,
    model: str,
    results: dict[str, dict],
    source: str,
    *,
    turn: int | None = None,
) -> None:
    """Batch helper — store N (criterion, result) pairs at one source/ts."""
    for crit, result in results.items():
        store(row, crit, model, result, source, turn=turn)


# --- aggregation -----------------------------------------------------------


def _aggregate(entries: list[dict]) -> dict:
    """Average numeric values; return latest rationale + counts in `raw`."""
    numeric = [e["value"] for e in entries if isinstance(e.get("value"), (int, float))]
    nulls = sum(1 for e in entries if e.get("value") is None)
    if not numeric:
        return {
            "value": None,
            "rationale": entries[-1].get("rationale", ""),
            "raw": {"_cached": True, "n_numeric": 0, "n_null": nulls},
        }
    avg = sum(numeric) / len(numeric)
    return {
        "value": avg,
        "rationale": entries[-1].get("rationale", ""),
        "raw": {
            "_cached": True,
            "n_numeric": len(numeric),
            "n_null": nulls,
            "ts_first": entries[0].get("ts"),
            "ts_last": entries[-1].get("ts"),
        },
    }


# --- the helper composers actually call -----------------------------------


async def cached_judge(
    row: dict | None,
    *,
    criterion_id: str,
    llm_fn: Any,
    messages: list[dict],
    task_info: dict,
    judge_client: Any,
    judge_model: str,
    sampling_args: dict[str, Any] | None = None,
    force_recall: bool = False,
    use_legacy_fallback: bool = True,
    composer_name: str = "",
    turn: int | None = None,
) -> dict:
    """LLM judge with row-level caching.

    Behavior:
    - `row=None` → caching disabled, behaves like a direct call.
    - `force_recall=True` → always calls the LLM, appends a new entry.
      Future reads return the mean of all entries (including this one).
    - Otherwise: returns `judge_cache` hit if any; else (only for
      outcome-level, `turn=None`) `judge_breakdown*` legacy hit; else
      calls the LLM and stores the result.

    `turn`:
    - `None` (default) → outcome-level cache lookup/store. This is what
      v1_llm_only / v2_hybrid / state_v1's outcome LLM path use.
    - `int k`         → per-turn cache lookup/store. The caller is
      responsible for slicing `messages` to the appropriate prefix
      before calling. Legacy fallback is disabled for per-turn lookups
      (legacy entries are outcome-only).
    """
    if row is not None and not force_recall:
        hit = lookup_cached(row, criterion_id, judge_model, turn=turn)
        if hit is not None:
            return hit
        # Legacy fallback only applies to outcome-level (turn=None).
        if use_legacy_fallback and turn is None:
            legacy = lookup_legacy(row, criterion_id)
            if legacy is not None:
                store(
                    row, criterion_id, judge_model,
                    {"value": legacy["value"], "rationale": legacy["rationale"]},
                    source=f"legacy:{legacy['source']}",
                    turn=None,
                )
                return {
                    "value": legacy["value"],
                    "rationale": legacy["rationale"],
                    "raw": {"_legacy": True, "_source": legacy["source"]},
                }

    result = await llm_fn.score(
        messages, task_info,
        judge_client=judge_client,
        judge_model=judge_model,
        sampling_args=sampling_args,
    )
    if row is not None:
        source = f"composer:{composer_name}" if composer_name else "composer_call"
        if force_recall:
            source = f"{source}:force_recall"
        if turn is not None:
            source = f"{source}:turn={turn}"
        store(row, criterion_id, judge_model, result, source=source, turn=turn)
    return result


__all__ = [
    "CACHE_KEY",
    "lookup_cached",
    "lookup_legacy",
    "store",
    "store_many",
    "cached_judge",
]
