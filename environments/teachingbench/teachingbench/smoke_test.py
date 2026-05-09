"""One-rollout smoke test.

Default mode is `--dry-run`: build the env, print the dataset row + system prompt + tool
defs, exit without API calls. Use `--live` to actually run a rollout (needs API keys).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from teachingbench.dataset import build_dataset


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TeachingBench smoke test (one rollout).")
    p.add_argument("--task", default=None, help="Task ID under teachingbench/tasks/.")
    p.add_argument("--tutor-model", default=None, help="Model id for the tutor under test.")
    p.add_argument("--judge-model", default="gpt-4.1-nano", help="Model for env-side LLM (student + grader).")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL (e.g. Prime Inference).")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Env var to read the API key from.")
    p.add_argument("--max-student-turns", type=int, default=8)
    p.add_argument("--live", action="store_true", help="Actually run a rollout. Default is dry-run.")
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    if not args.live:
        await dry_run(args)
        return

    if not args.tutor_model:
        sys.exit("--tutor-model is required for --live")
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        sys.exit(f"${args.api_key_env} is not set; needed for --live")

    from openai import AsyncOpenAI

    from teachingbench.env import load_environment

    client = AsyncOpenAI(api_key=api_key, base_url=args.base_url) if args.base_url else AsyncOpenAI(api_key=api_key)

    env = load_environment(
        judge_client=client,
        judge_model=args.judge_model,
        student_client=client,
        student_model=args.judge_model,
        max_student_turns=args.max_student_turns,
        task_filter=args.task,
    )

    print(f"Loaded env: {type(env).__name__}")
    print(f"Dataset rows: {len(env.dataset)}")
    print(f"Tutor model: {args.tutor_model}")
    print("Running one rollout...\n")

    # Use the env's evaluation entry point. `evaluate` runs rollouts and returns scored outputs.
    # If your verifiers version exposes `generate` / `rollout` instead, swap accordingly.
    if hasattr(env, "evaluate"):
        outputs = await env.evaluate(client=client, model=args.tutor_model, num_rollouts=1)
    else:
        outputs = await env.generate(client=client, model=args.tutor_model, num_rollouts=1)

    _print_outputs(outputs)


async def dry_run(args: argparse.Namespace) -> None:
    print("=== TeachingBench dry-run ===")
    dataset = build_dataset(task_filter=args.task)
    print(f"Tasks loaded: {len(dataset)}")
    for i, row in enumerate(dataset):
        info = json.loads(row["info"])
        print(f"\n--- Task {i}: {info['task_id']} ---")
        print(f"Subject: {info['subject']}")
        print(f"Topic:   {info['topic']}")
        print(f"Difficulty: {info['difficulty']}")
        print(f"Materials length: {len(info['materials'])} chars")
        print(f"Seed question (first 200 chars): {row['question'][:200]}...")

    from teachingbench.tools import TOOLS

    print(f"\nTools registered: {[getattr(t, '__name__', '?') for t in TOOLS]}")

    # Validate the env import path works (catches missing deps early).
    try:
        from teachingbench.env import load_environment  # noqa: F401
        from teachingbench.grader.judge import TeachingRubric  # noqa: F401

        print("Env + rubric imports: OK")
    except Exception as e:
        print(f"Env import failed: {e}")
        raise

    print("\nDry-run OK. Pass --live and --tutor-model to actually run a rollout.")


def _print_outputs(outputs: Any) -> None:
    print("\n=== Rollout complete ===")
    if hasattr(outputs, "states") and outputs.states:
        state = outputs.states[0]
        breakdown = state.get("reward_breakdown", {}) if isinstance(state, dict) else {}
        print(f"Composite reward:   {breakdown.get('composite', 0.0):.3f}")
        print(f"  Quiz score:       {breakdown.get('quiz_score', 0.0):.3f}")
        print(f"  Self-rating:      {breakdown.get('self_rating_score', 0.0):.3f}")
        print(f"  Quiz items:       {len(breakdown.get('per_item', []))}")
        finalize_reason = state.get("finalize_reason") if isinstance(state, dict) else None
        if finalize_reason:
            print(f"  Finalize reason:  {finalize_reason}")
    else:
        print(repr(outputs)[:2000])


if __name__ == "__main__":
    asyncio.run(main())
