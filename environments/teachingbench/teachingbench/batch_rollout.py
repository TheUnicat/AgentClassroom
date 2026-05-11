"""Batch rollout runner — runs (task × model × replica) rollouts WITHOUT
calling the judge, and saves transcripts for later batch judging.

Use this when you want to:
- Decouple rollout cost (real-time API) from judge cost (often big & batchable)
- Run all rollouts today, defer judging to tomorrow (OpenAI Batch API gives
  50% off + typically returns in 1–6 hours, max 24h)
- Iterate on the rubric without re-running rollouts

What it saves: each cell goes into `outputs/runs/batch_<TIMESTAMP>/<tutor>__<task>/`,
which contains `results.jsonl` (one record per rollout, with prompt + completion).
The judge will populate `judge_breakdown` later — for now those records have
`reward=0.0` and a `skipped: true` flag in the breakdown.

Usage:
    python -m teachingbench.batch_rollout \\
        --tutor-models gpt-5.4-nano gpt-5.4-mini gpt-5.4 \\
        --task-ids all \\
        --rollouts-per-cell 4 \\
        --student-model gpt-5.4-mini \\
        --max-concurrent 8

Notes:
- `--task-ids all` runs every discoverable task (currently 57).
- `--task-ids cs/big_o_notation math/derivative_what_it_measures ...` for a subset.
- Concurrency is per-cell; the script iterates over cells sequentially.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from teachingbench.client_utils import detect_provider, tutor_client_for
from teachingbench.dataset import build_dataset
from teachingbench.env import load_environment

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNS_ROOT = REPO_ROOT / "environments" / "teachingbench" / "outputs" / "runs"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--tutor-models", required=True, nargs="+",
        help="Space-separated list of tutor models to run.",
    )
    p.add_argument(
        "--task-ids", required=True, nargs="+",
        help='Space-separated task IDs, OR the literal string "all".',
    )
    p.add_argument(
        "--rollouts-per-cell", type=int, default=2,
        help="Number of rollouts per (tutor, task) cell. Default: 2.",
    )
    p.add_argument(
        "--student-model", default=None,
        help="Student LLM model. Defaults to gpt-5.4-mini.",
    )
    p.add_argument(
        "--judge-model", default=os.environ.get("DEFAULT_JUDGE_MODEL", "gpt-5.4"),
        help="(Unused in batch_rollout — skip-judge is forced on. Kept for log clarity.)",
    )
    p.add_argument(
        "--max-concurrent", type=int, default=8,
        help="Max parallel rollouts per cell. Default: 8.",
    )
    p.add_argument("--api-key-env", default="OPENAI_API_KEY")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL override.")
    p.add_argument(
        "--output-root", default=None,
        help=f"Where to save the batch. Default: {DEFAULT_RUNS_ROOT}/batch_<timestamp>/",
    )
    p.add_argument(
        "--default-turns", type=int, default=4,
        help="Fallback turn count for tasks that don't specify turns in meta.yaml.",
    )
    return p.parse_args()


def expand_task_ids(raw: list[str]) -> list[str]:
    if raw == ["all"]:
        rows = build_dataset()
        ids = []
        for r in rows:
            info = json.loads(r["info"]) if isinstance(r["info"], str) else r["info"]
            ids.append(info["task_id"])
        return sorted(ids)
    return list(raw)


async def run_cell(
    *,
    tutor_model: str,
    task_id: str,
    rollouts: int,
    tutor_client: ClientConfig,
    env_client: AsyncOpenAI,
    student_model: str,
    judge_model: str,
    max_concurrent: int,
    cell_results_path: Path,
    default_turns: int,
) -> dict[str, Any]:
    env = load_environment(
        judge_client=env_client,
        judge_model=judge_model,
        student_client=env_client,
        student_model=student_model,
        default_turns=default_turns,
        task_filter=task_id,
        skip_judge=True,
    )
    cell_results_path.mkdir(parents=True, exist_ok=True)
    outputs = await env.evaluate(
        client=tutor_client,
        model=tutor_model,
        num_examples=1,
        rollouts_per_example=rollouts,
        state_columns=["judge_breakdown"],
        max_concurrent=max_concurrent,
        save_results=True,
        results_path=cell_results_path,
    )
    rollouts_out = outputs.get("outputs", []) if isinstance(outputs, dict) else []
    return {
        "task_id": task_id,
        "tutor_model": tutor_model,
        "n_rollouts": len(rollouts_out),
        "results_path": str(cell_results_path),
        "errors": sum(1 for r in rollouts_out if r.get("error")),
    }


async def main() -> None:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        sys.exit(f"${args.api_key_env} is not set (needed for student + judge models)")

    # Verify Anthropic key is present if any tutor model is claude-*
    needs_anthropic = any(detect_provider(m) == "anthropic" for m in args.tutor_models)
    if needs_anthropic and not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("$ANTHROPIC_API_KEY is not set (needed for claude-* tutor models)")

    base_url = args.base_url or "https://api.openai.com/v1"
    env_client = AsyncOpenAI(api_key=api_key, base_url=base_url)  # student + judge stay OpenAI
    student_model = args.student_model or "gpt-5.4-mini"

    task_ids = expand_task_ids(args.task_ids)

    if args.output_root:
        output_root = Path(args.output_root)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_root = DEFAULT_RUNS_ROOT / f"batch_{ts}"
    output_root.mkdir(parents=True, exist_ok=True)

    plan = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tutor_models": args.tutor_models,
        "task_ids": task_ids,
        "rollouts_per_cell": args.rollouts_per_cell,
        "student_model": student_model,
        "judge_model_for_later": args.judge_model,
        "max_concurrent": args.max_concurrent,
        "total_cells": len(args.tutor_models) * len(task_ids),
        "total_rollouts": len(args.tutor_models) * len(task_ids) * args.rollouts_per_cell,
        "output_root": str(output_root),
    }
    (output_root / "batch_plan.json").write_text(json.dumps(plan, indent=2))
    print(json.dumps(plan, indent=2))
    print()

    # Iterate over cells sequentially; rollouts within a cell are parallel.
    summaries: list[dict[str, Any]] = []
    cell_idx = 0
    for tutor in args.tutor_models:
        tutor_client = tutor_client_for(tutor)
        provider = detect_provider(tutor)
        for task_id in task_ids:
            cell_idx += 1
            slug = task_id.replace("/", "__")
            cell_path = output_root / f"{tutor}__{slug}"
            print(f"[{cell_idx}/{plan['total_cells']}] tutor={tutor} ({provider})  task={task_id}")
            try:
                summary = await run_cell(
                    tutor_model=tutor,
                    task_id=task_id,
                    rollouts=args.rollouts_per_cell,
                    tutor_client=tutor_client,
                    env_client=env_client,
                    student_model=student_model,
                    judge_model=args.judge_model,
                    max_concurrent=args.max_concurrent,
                    cell_results_path=cell_path,
                    default_turns=args.default_turns,
                )
                print(f"  → {summary['n_rollouts']} rollouts saved; errors={summary['errors']}")
                summaries.append(summary)
            except Exception as e:
                print(f"  ✗ cell failed: {e}")
                summaries.append({
                    "task_id": task_id, "tutor_model": tutor,
                    "n_rollouts": 0, "results_path": str(cell_path), "error": str(e),
                })

    (output_root / "batch_summary.json").write_text(json.dumps(summaries, indent=2))
    print()
    print(f"Done. Batch root: {output_root}")
    print(f"To judge later, point at each cell's results.jsonl with judge_reliability_check.py --n 1.")


if __name__ == "__main__":
    asyncio.run(main())
