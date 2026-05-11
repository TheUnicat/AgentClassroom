"""Task (full-pipeline) reliability check.

Runs the FULL rollout pipeline N times for the same task — different student
LLM responses, different tutor seeds, fresh judge call each time. Captures
total system noise (student behavior + tutor temperature + judge variance
combined). Use this AFTER `judge_reliability_check` confirms the judge alone
is stable on a fixed transcript.

Each trial gets ONE judge call (not multiple judge replays). If task scores
are noisy here BUT judge_reliability_check showed the judge is stable on a
fixed transcript, the noise is in the rollout itself (student behavior /
tutor variation), not the judge.

Usage:
    python -m teachingbench.task_reliability_check \\
        --task-id cs/intro_python_hello_world \\
        --tutor-model gpt-5.4-mini \\
        --n 6 \\
        [--student-model gpt-5.4-mini] \\
        [--judge-model gpt-5.4] \\
        [--max-concurrent 4]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from verifiers.types import ClientConfig

from teachingbench._reliability_helpers import print_reliability_table
from teachingbench.dataset import discover_tasks, load_task
from teachingbench.env import load_environment
from teachingbench.prompts import DEFAULT_RUBRIC

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNS_ROOT = REPO_ROOT / "environments" / "teachingbench" / "outputs" / "runs"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--task-id", required=True, help="e.g. cs/intro_python_hello_world")
    p.add_argument("--tutor-model", required=True, help="Model under test (acts as the tutor).")
    p.add_argument("--student-model", default=None, help="Defaults to --judge-model.")
    p.add_argument(
        "--judge-model",
        default=os.environ.get("DEFAULT_JUDGE_MODEL", "gpt-5.4"),
        help="One judge call per trial. Default: $DEFAULT_JUDGE_MODEL or gpt-5.4.",
    )
    p.add_argument("--n", type=int, default=6, help="Number of full rollouts. Default: 6.")
    p.add_argument(
        "--max-concurrent",
        type=int,
        default=-1,
        help="Cap on simultaneous rollouts (-1 = no cap). Default: -1.",
    )
    p.add_argument("--api-key-env", default="OPENAI_API_KEY")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL override.")
    p.add_argument(
        "--save",
        default=None,
        help="Optional path to write per-trial breakdowns as JSONL.",
    )
    p.add_argument(
        "--no-save-runs",
        action="store_true",
        help="Don't persist the N rollouts to outputs/runs/ (default: save them).",
    )
    return p.parse_args()


def find_task_meta(task_id: str) -> dict[str, Any]:
    """Locate the task by id and return its loaded info (including rubric)."""
    for task_dir in discover_tasks():
        loaded = load_task(task_dir)
        if loaded["task_id"] == task_id:
            return loaded
    raise SystemExit(f"Task not found: {task_id!r}. Available: {[load_task(d)['task_id'] for d in discover_tasks()]}")


async def run_trials(
    *,
    task_id: str,
    n: int,
    tutor_client: ClientConfig,
    tutor_model: str,
    judge_client: AsyncOpenAI,
    judge_model: str,
    student_client: AsyncOpenAI,
    student_model: str,
    max_concurrent: int,
    save_results: bool,
    results_path: Path | None,
) -> dict[str, Any]:
    """One env.evaluate call with rollouts_per_example=n. Verifiers handles the
    parallelism / max_concurrent gating internally."""
    env = load_environment(
        judge_client=judge_client,
        judge_model=judge_model,
        student_client=student_client,
        student_model=student_model,
        task_filter=task_id,
    )
    print(
        f"Running {n} full rollouts of {task_id}\n"
        f"  tutor={tutor_model}  student={student_model}  judge={judge_model}\n"
        f"  max_concurrent={max_concurrent}  save_runs={save_results}"
    )
    return await env.evaluate(
        client=tutor_client,
        model=tutor_model,
        num_examples=1,
        rollouts_per_example=n,
        state_columns=["judge_breakdown"],
        max_concurrent=max_concurrent,
        save_results=save_results,
        results_path=results_path,
    )


async def main() -> None:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"${args.api_key_env} is not set")

    task = find_task_meta(args.task_id)
    rubric = task["rubric"] if isinstance(task.get("rubric"), list) and task["rubric"] else DEFAULT_RUBRIC
    criterion_ids = [c["id"] for c in rubric]

    base_url = args.base_url or "https://api.openai.com/v1"
    env_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    tutor_client = ClientConfig(
        client_type="openai_chat_completions",
        api_key_var=args.api_key_env,
        api_base_url=base_url,
    )
    student_model = args.student_model or args.judge_model

    if args.no_save_runs:
        results_path = None
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        slug = args.task_id.replace("/", "__")
        results_path = DEFAULT_RUNS_ROOT / f"{ts}__taskreliability__{slug}__{args.tutor_model}__n{args.n}"
        results_path.mkdir(parents=True, exist_ok=True)

    outputs = await run_trials(
        task_id=args.task_id,
        n=args.n,
        tutor_client=tutor_client,
        tutor_model=args.tutor_model,
        judge_client=env_client,
        judge_model=args.judge_model,
        student_client=env_client,
        student_model=student_model,
        max_concurrent=args.max_concurrent,
        save_results=not args.no_save_runs,
        results_path=results_path,
    )

    rollouts = outputs.get("outputs", []) if isinstance(outputs, dict) else []
    if not rollouts:
        raise SystemExit("No rollouts produced; check the env config.")

    # Extract per-trial breakdowns
    per_trial_scores: list[dict[str, float | None]] = []
    per_trial_composites: list[float] = []
    errors: list[str] = []
    for i, r in enumerate(rollouts):
        breakdown = r.get("judge_breakdown") or {}
        if not isinstance(breakdown, dict):
            breakdown = {}
        scores_raw = breakdown.get("scores") or {}
        per_trial_scores.append({k: v for k, v in scores_raw.items()})
        reward = r.get("reward")
        if isinstance(reward, (int, float)):
            per_trial_composites.append(float(reward))
        err = r.get("error")
        if err:
            errors.append(f"trial {i}: {err}")

    print_reliability_table(
        title=f"Task reliability — n={args.n}",
        context_lines=[
            f"Task:     {args.task_id}",
            f"Topic:    {task.get('topic', '')}",
            f"Tutor:    {args.tutor_model}",
            f"Student:  {student_model}",
            f"Judge:    {args.judge_model}  (one-shot per trial)",
            f"Per-trial composites: {[round(c, 3) for c in per_trial_composites]}",
        ],
        criterion_ids=criterion_ids,
        per_trial_scores=per_trial_scores,
        per_trial_composites=per_trial_composites,
        n=args.n,
        errors=errors,
    )

    if args.save:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            for ts, comp, r in zip(per_trial_scores, per_trial_composites, rollouts):
                f.write(json.dumps({"scores": ts, "composite": comp, "stop_condition": r.get("stop_condition")}) + "\n")
        print(f"\nPer-trial breakdowns written to: {out_path}")

    if results_path:
        print(f"Saved {len(rollouts)} rollout(s) to: {results_path}")


if __name__ == "__main__":
    asyncio.run(main())
