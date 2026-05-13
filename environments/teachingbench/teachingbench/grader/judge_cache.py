"""Per-row judgment cache.

A `results.jsonl` row can carry a `judge_cache` blob alongside its
`judge_breakdown*` keys:

    row["judge_cache"] = {
        "<criterion_id>": {
            "<judge_model>": [
                {"value": float | None,
                 "rationale": str,
                 "source": str,
                 "ts": float},
                ...
            ]
        }
    }

Reading:
- `lookup_cached(row, crit, model)` returns an aggregated result over
  all entries matching `(crit, model)` — averaging numeric `value`s,
  carrying the most recent rationale, attaching counts in `raw`. None
  if there are no matching entries.
- `lookup_legacy(row, crit)` falls back to scanning `judge_breakdown`
  and any `judge_breakdown__*` for that criterion's score, so v1's
  batched scores are reused without re-judging. Model isn't recorded
  in legacy buckets so we accept any match.

Writing:
- `store(row, crit, model, result, source)` appends a new entry. Source
  is a short label like `composer:v2_hybrid` or `runner:force-recall`.

Why averaging on read:
- Re-judging a criterion (e.g. `--force-recall`) writes a NEW entry
  rather than overwriting. Subsequent reads return the mean of all
  recorded values, giving cheap noise reduction when you've spent the
  cycles to judge twice.

Why the legacy fallback:
- Most rollouts in the 228-baseline already have v1's batched
  `judge_breakdown.scores`. For a composer that wants e.g. only
  `answers_the_question`, scanning that bucket avoids a redundant LLM
  call. After the legacy hit we also write it into `judge_cache` so
  later reads are a single dict lookup, not a multi-bucket scan.
"""

from __future__ import annotations

import time
from typing import Any

CACHE_KEY = "judge_cache"


# --- raw cache access ------------------------------------------------------


def _entries(row: dict, criterion: str, model: str) -> list[dict]:
    return (
        row.get(CACHE_KEY, {})
        .get(criterion, {})
        .get(model, [])
    )


def lookup_cached(row: dict, criterion: str, model: str) -> dict | None:
    """Aggregated result for (criterion, model), or None if no entries.

    Returned dict has the same `{value, rationale, raw}` shape that an LLM
    function would return, so the caller can use it interchangeably.
    """
    entries = _entries(row, criterion, model)
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


def store(row: dict, criterion: str, model: str, result: dict, source: str) -> None:
    """Append a new entry to the cache for (criterion, model)."""
    cache = row.setdefault(CACHE_KEY, {})
    by_crit = cache.setdefault(criterion, {})
    entries = by_crit.setdefault(model, [])
    entries.append({
        "value": result.get("value"),
        "rationale": str(result.get("rationale") or ""),
        "source": source,
        "ts": time.time(),
    })


def store_many(row: dict, model: str, results: dict[str, dict], source: str) -> None:
    """Batch helper — store N (criterion, result) pairs at one source/ts."""
    for crit, result in results.items():
        store(row, crit, model, result, source)


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
) -> dict:
    """LLM judge with row-level caching.

    Behavior:
    - `row=None` → caching disabled, behaves like a direct call.
    - `force_recall=True` → always calls the LLM, appends a new entry.
      Future reads return the mean of all entries (including this one).
    - Otherwise: returns `judge_cache` hit if any; else `judge_breakdown*`
      legacy hit (if `use_legacy_fallback`); else calls the LLM and
      stores the result.
    """
    if row is not None and not force_recall:
        hit = lookup_cached(row, criterion_id, judge_model)
        if hit is not None:
            return hit
        if use_legacy_fallback:
            legacy = lookup_legacy(row, criterion_id)
            if legacy is not None:
                store(
                    row, criterion_id, judge_model,
                    {"value": legacy["value"], "rationale": legacy["rationale"]},
                    source=f"legacy:{legacy['source']}",
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
        store(row, criterion_id, judge_model, result, source=source)
    return result


__all__ = [
    "CACHE_KEY",
    "lookup_cached",
    "lookup_legacy",
    "store",
    "store_many",
    "cached_judge",
]
