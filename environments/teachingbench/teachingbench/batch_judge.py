"""Batched judging via Anthropic Message Batches API.

Submits one judge call per saved rollout as a single batch. Cache-control is
set on the system message (instructions + rubric) and tool definition so the
~4.6k tokens of fixed content cost ~10% per call after the first. Output
tokens still pay full batched rate but they're only ~1k each.

Reads from one or more run directories (e.g. `outputs/runs/batched_*`,
`outputs/runs/batch_realtime_round1`) — each must contain
`<model>__<task>/results.jsonl` cells. Writes the resulting judge_breakdown
back into each rollout's results.jsonl in place.

Usage:
    python -m teachingbench.batch_judge \\
        --rollout-dirs outputs/runs/batch_realtime_round1 \\
                      outputs/runs/batched_gpt54_round1_v2 \\
                      outputs/runs/batched_opus_round1_text \\
                      outputs/runs/batched_opus_round1_materials \\
        --judge-model claude-opus-4-7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from teachingbench.grader.judge import _build_response_schema, _format_rubric, _render_transcript
from teachingbench.grader.reward_scoring import compute_composite, describe as describe_formula
from teachingbench.prompts import DEFAULT_RUBRIC

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rollout-dirs", required=True, nargs="+",
                   help="One or more run directories. Each contains <model>__<task>/results.jsonl cells.")
    p.add_argument("--judge-model", default="claude-opus-4-7")
    p.add_argument("--poll-interval", type=int, default=60)
    p.add_argument("--api-key-env", default="ANTHROPIC_API_KEY")
    p.add_argument("--summary-out", default=None,
                   help="Optional path to dump a per-rollout summary as JSONL.")
    p.add_argument("--skip-already-judged", action="store_true",
                   help="Skip cells whose judge_breakdown.skipped is not True (i.e. already judged).")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Build the static (cacheable) parts of the prompt once.
# ---------------------------------------------------------------------------


def build_static_pieces(rubric: list[dict]) -> tuple[str, dict, dict]:
    """Return (system_text, tool_def, schema) — identical across all rollouts."""
    schema = _build_response_schema(rubric)
    system_text = (
        "You are grading a tutoring session against a fixed rubric.\n\n"
        "Rubric (score each criterion in [0, 1]):\n"
        f"{_format_rubric(rubric)}\n\n"
        "Score each criterion independently on its own merits; the composite is computed "
        "downstream as a weighted combination, so do not try to weight or compensate across "
        "criteria yourself. The anchors are calibration points, not the only allowed values — "
        "interpolate freely between them. For each criterion, return either a number in [0, 1] "
        "OR null (if the criterion doesn't apply to this transcript — see each criterion's "
        "description for when null is appropriate). Submit your scores via the "
        "`report_rubric_scores` tool."
    )
    tool_def = {
        "name": "report_rubric_scores",
        "description": "Submit per-criterion rubric scores and an overall rationale.",
        "input_schema": schema,
        "cache_control": {"type": "ephemeral"},
    }
    return system_text, tool_def, schema


def build_user_message(rec: dict, transcript: str) -> str:
    """The variable per-rollout portion of the prompt."""
    info = rec.get("info") or {}
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except json.JSONDecodeError:
            info = {}
    topic = info.get("topic", "")
    materials = info.get("materials", "")
    return (
        f"Topic: {topic}\n\n"
        f"Materials the student had:\n<materials>\n{materials}\n</materials>\n\n"
        f"Transcript:\n<transcript>\n{transcript}\n</transcript>"
    )


# ---------------------------------------------------------------------------
# Walk run directories, build requests
# ---------------------------------------------------------------------------


def find_rollouts(dirs: list[Path]) -> list[tuple[str, Path, dict]]:
    """Return list of (custom_id, results_jsonl_path, parsed_record)."""
    out: list[tuple[str, Path, dict]] = []
    idx = 0
    for run_dir in dirs:
        run_dir = Path(run_dir)
        if not run_dir.is_dir():
            logger.warning("Skipping non-existent dir: %s", run_dir)
            continue
        for cell_dir in sorted(run_dir.iterdir()):
            if not cell_dir.is_dir():
                continue
            results_path = cell_dir / "results.jsonl"
            if not results_path.is_file():
                continue
            try:
                rec = json.loads(results_path.read_text().splitlines()[0])
            except (json.JSONDecodeError, IndexError) as e:
                logger.warning("Bad results.jsonl at %s: %s", results_path, e)
                continue
            out.append((f"r{idx:04d}", results_path, rec))
            idx += 1
    return out


def build_batch_requests(
    rollouts: list[tuple[str, Path, dict]],
    rubric: list[dict],
    judge_model: str,
) -> list[dict]:
    system_text, tool_def, _ = build_static_pieces(rubric)
    requests = []
    for custom_id, _path, rec in rollouts:
        transcript = _render_transcript(rec.get("prompt", []), rec.get("completion", []))
        user_text = build_user_message(rec, transcript)
        params: dict[str, Any] = {
            "model": judge_model,
            "max_tokens": 4096,
            "system": [{"type": "text", "text": system_text,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user_text}],
            "tools": [tool_def],
            "tool_choice": {"type": "tool", "name": "report_rubric_scores"},
        }
        requests.append({"custom_id": custom_id, "params": params})
    return requests


# ---------------------------------------------------------------------------
# Submit, poll, fetch, parse
# ---------------------------------------------------------------------------


async def submit_and_wait(client: AsyncAnthropic, requests: list[dict], poll_interval: int) -> str:
    batch = await client.messages.batches.create(requests=requests)
    logger.info("Submitted batch: %s (%d requests)", batch.id, len(requests))
    while True:
        b = await client.messages.batches.retrieve(batch.id)
        status = b.processing_status
        logger.info("Batch %s status=%s", b.id, status)
        if status == "ended":
            return batch.id
        if status in ("canceling", "expired"):
            raise RuntimeError(f"Batch terminated abnormally: status={status}")
        await asyncio.sleep(poll_interval)


def extract_tool_input(message_content: list) -> Any:
    for block in message_content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_rubric_scores":
            tool_input = block.input
            if isinstance(tool_input, dict):
                return tool_input
            try:
                return json.loads(tool_input)
            except (json.JSONDecodeError, TypeError):
                return None
    return None


def build_breakdown(parsed: dict, rubric: list[dict]) -> dict[str, Any]:
    """Convert raw parsed judge output → judge_breakdown record matching judge_transcript."""
    raw_scores = parsed.get("scores") or {}
    if isinstance(raw_scores, str):
        try:
            raw_scores = json.loads(raw_scores)
        except json.JSONDecodeError:
            raw_scores = {}
    if not isinstance(raw_scores, dict):
        raw_scores = {}

    scores: dict[str, float | None] = {}
    weights: dict[str, float] = {}
    for c in rubric:
        cid = c["id"]
        v = raw_scores.get(cid)
        scores[cid] = None if v is None else max(0.0, min(1.0, float(v)))
        w = c.get("weight")
        weights[cid] = float(w) if isinstance(w, (int, float)) else 1.0 / len(rubric)

    composite_result = compute_composite(scores, weights)
    return {
        "scores": scores,
        "weights": weights,
        "rationale": str(parsed.get("rationale") or ""),
        "composite": composite_result["composite"],
        "composite_raw": composite_result["composite_raw"],
        "composite_terms": composite_result["terms"],
        "formula": describe_formula(),
        "rubric": rubric,
    }


async def process_results(
    client: AsyncAnthropic,
    batch_id: str,
    rollout_map: dict[str, tuple[Path, dict]],
    rubric: list[dict],
    summary_out: Path | None,
) -> dict[str, Any]:
    """Stream batch results, parse, write back to each results.jsonl. Returns summary stats."""
    stats = {"succeeded": 0, "errored": 0, "missing": 0, "total": len(rollout_map)}
    summary_records = []

    seen_ids: set[str] = set()
    async for result in await client.messages.batches.results(batch_id):
        cid = result.custom_id
        seen_ids.add(cid)
        if cid not in rollout_map:
            logger.warning("Result for unknown custom_id %s — skipping", cid)
            continue
        path, rec = rollout_map[cid]

        if result.result.type == "succeeded":
            parsed = extract_tool_input(result.result.message.content)
            if parsed is None:
                rec["judge_breakdown"] = {"skipped": False, "error": "no_tool_use", "scores": {}, "composite": 0.0}
                rec["reward"] = 0.0
                stats["errored"] += 1
            else:
                breakdown = build_breakdown(parsed, rubric)
                rec["judge_breakdown"] = breakdown
                rec["reward"] = breakdown["composite"]
                stats["succeeded"] += 1
        else:
            err = getattr(result.result, "error", None) or str(result.result.type)
            rec["judge_breakdown"] = {"skipped": False, "error": str(err), "scores": {}, "composite": 0.0}
            rec["reward"] = 0.0
            stats["errored"] += 1

        path.write_text(json.dumps(rec) + "\n")
        summary_records.append({
            "custom_id": cid,
            "task_id": (rec.get("info") if isinstance(rec.get("info"), dict) else {}).get("task_id"),
            "tutor_model": rec.get("tutor_model") or path.parent.name.split("__")[0],
            "composite": rec.get("reward"),
            "path": str(path),
        })

    # Anything in rollout_map without a result is "missing"
    stats["missing"] = stats["total"] - len(seen_ids)

    if summary_out is not None:
        summary_out.parent.mkdir(parents=True, exist_ok=True)
        with summary_out.open("w") as f:
            for r in summary_records:
                f.write(json.dumps(r) + "\n")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "openai", "anthropic", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        sys.exit(f"${args.api_key_env} is not set")
    client = AsyncAnthropic(api_key=api_key)

    rubric = DEFAULT_RUBRIC
    rollouts = find_rollouts([Path(d) for d in args.rollout_dirs])
    if args.skip_already_judged:
        before = len(rollouts)
        rollouts = [
            (cid, p, rec) for cid, p, rec in rollouts
            if not (isinstance(rec.get("judge_breakdown"), dict) and not rec["judge_breakdown"].get("skipped", True))
        ]
        logger.info("--skip-already-judged: %d → %d rollouts", before, len(rollouts))

    logger.info("Found %d rollouts to judge", len(rollouts))
    if not rollouts:
        sys.exit("Nothing to judge.")

    rollout_map = {cid: (path, rec) for cid, path, rec in rollouts}
    requests = build_batch_requests(rollouts, rubric, args.judge_model)

    batch_id = await submit_and_wait(client, requests, args.poll_interval)
    logger.info("Batch ended — fetching results...")
    stats = await process_results(
        client, batch_id, rollout_map, rubric,
        Path(args.summary_out) if args.summary_out else None,
    )
    logger.info("Done. Stats: %s", stats)


if __name__ == "__main__":
    asyncio.run(main())
