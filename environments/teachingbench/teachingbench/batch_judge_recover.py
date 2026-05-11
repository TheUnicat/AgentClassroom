"""Recover scores from a previously-completed Anthropic batch when the model
emitted XML-style parameter tags inside tool input (a known Opus 4.7 quirk).

Symptom: tool input has `scores` as a string like `\\n<parameter name="x">0.9`
with the rest of the criteria leaked to the top level of the dict.

Usage:
    python -m teachingbench.batch_judge_recover \\
        --batch-id msgbatch_019y6e2aeWfd1beMWad2WBCp \\
        --summary outputs/runs/judge_round1_summary.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic

from teachingbench.batch_judge import build_breakdown, extract_tool_input
from teachingbench.prompts import DEFAULT_RUBRIC

logger = logging.getLogger(__name__)

XML_PARAM_RE = re.compile(r'<parameter name="(\w+)">([0-9.eE+-]+|null)')


def recover_malformed(parsed: dict, rubric_ids: list[str]) -> dict:
    """If `scores` is a string with XML param tags, recover the dict form."""
    if not isinstance(parsed, dict):
        return parsed
    scores_field = parsed.get("scores")
    if not isinstance(scores_field, str) or "<parameter" not in scores_field:
        return parsed

    recovered: dict[str, Any] = {}

    # Extract the first criterion (whichever is referenced in the XML tag).
    m = XML_PARAM_RE.search(scores_field)
    if m:
        cid, raw_val = m.group(1), m.group(2)
        recovered[cid] = None if raw_val == "null" else float(raw_val)

    # Pick up top-level criterion values (everything except known meta fields).
    for k, v in parsed.items():
        if k in ("rationale", "scores"):
            continue
        if k in rubric_ids and (v is None or isinstance(v, (int, float))):
            recovered[k] = v

    return {"scores": recovered, "rationale": parsed.get("rationale", "")}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--batch-id", required=True, help="Anthropic message batch ID to re-process.")
    p.add_argument("--summary", required=True, help="judge_round1_summary.jsonl from the original run.")
    p.add_argument("--api-key-env", default="ANTHROPIC_API_KEY")
    return p.parse_args()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for noisy in ("httpx", "openai", "anthropic", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        sys.exit(f"${args.api_key_env} is not set")

    # Load summary to map custom_id → results.jsonl path
    summary = {}
    for line in Path(args.summary).read_text().splitlines():
        rec = json.loads(line)
        summary[rec["custom_id"]] = rec

    rubric = DEFAULT_RUBRIC
    rubric_ids = [c["id"] for c in rubric]

    client = AsyncAnthropic(api_key=api_key)
    n_recovered = 0
    n_still_failed = 0
    n_no_recovery_needed = 0
    fixed_records = []

    async for result in await client.messages.batches.results(args.batch_id):
        cid = result.custom_id
        if cid not in summary:
            continue
        if result.result.type != "succeeded":
            continue

        # Extract the tool input — same as before
        parsed = extract_tool_input(result.result.message.content)
        if parsed is None:
            n_still_failed += 1
            continue

        # Apply recovery if needed
        recovered = recover_malformed(parsed, rubric_ids)
        was_malformed = recovered is not parsed and recovered.get("scores")

        # Build breakdown
        breakdown = build_breakdown(recovered, rubric)

        # Skip if not interesting (i.e., not malformed AND already produced scores)
        path = Path(summary[cid]["path"])
        if not path.is_file():
            continue
        full_rec = json.loads(path.read_text().splitlines()[0])

        prev_composite = full_rec.get("reward") or 0.0
        new_composite = breakdown["composite"]

        # Only overwrite if recovery yielded something better (more non-null scores)
        prev_scores = (full_rec.get("judge_breakdown") or {}).get("scores") or {}
        prev_n_nonnull = sum(1 for v in prev_scores.values() if isinstance(v, (int, float)))
        new_n_nonnull = sum(1 for v in breakdown["scores"].values() if isinstance(v, (int, float)))

        if new_n_nonnull > prev_n_nonnull:
            full_rec["judge_breakdown"] = breakdown
            full_rec["reward"] = new_composite
            path.write_text(json.dumps(full_rec) + "\n")
            n_recovered += 1
            summary[cid]["composite"] = new_composite
            fixed_records.append({
                "custom_id": cid, "task_id": summary[cid]["task_id"],
                "tutor": summary[cid]["tutor_model"], "was_malformed": was_malformed,
                "prev_composite": prev_composite, "new_composite": new_composite,
            })
        else:
            n_no_recovery_needed += 1

    # Rewrite summary file
    with Path(args.summary).open("w") as f:
        for cid in sorted(summary.keys()):
            f.write(json.dumps(summary[cid]) + "\n")

    print(f"\nRecovered: {n_recovered}")
    print(f"No recovery needed: {n_no_recovery_needed}")
    print(f"Still failed: {n_still_failed}")
    print(f"\nRecovered rollouts:")
    for r in sorted(fixed_records, key=lambda r: -r["new_composite"]):
        print(f"  {r['tutor']:20s} / {r['task_id']:45s} {r['prev_composite']:.3f} → {r['new_composite']:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
