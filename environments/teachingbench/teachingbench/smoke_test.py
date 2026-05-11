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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from teachingbench.dataset import build_dataset

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RESULTS_ROOT = REPO_ROOT / "environments" / "teachingbench" / "outputs" / "runs"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="TeachingBench smoke test (one rollout).")
    p.add_argument("--task", default=None, help="Task ID under teachingbench/tasks/.")
    p.add_argument("--tutor-model", default=None, help="Model id for the tutor under test.")
    p.add_argument("--judge-model", default="gpt-5.4", help="Model for the LLM judge.")
    p.add_argument("--student-model", default=None, help="Model for the simulated student. Defaults to --judge-model.")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL (e.g. Prime Inference).")
    p.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Env var to read the API key from.")
    p.add_argument("--default-turns", type=int, default=4, help="Fallback turn count for tasks that don't specify `turns:` in meta.yaml.")
    p.add_argument("--results-dir", default=None, help=f"Where to save results. Default: {DEFAULT_RESULTS_ROOT}/<timestamp>/")
    p.add_argument("--no-save", action="store_true", help="Don't save results to disk (default: save).")
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
    from verifiers.types import ClientConfig

    from teachingbench.env import load_environment

    # Env-side LLM (student + grader): raw AsyncOpenAI — our code calls .chat.completions.create directly.
    env_client = AsyncOpenAI(api_key=api_key, base_url=args.base_url) if args.base_url else AsyncOpenAI(api_key=api_key)

    # Tutor client: verifiers wants a ClientConfig (or its own Client wrapper).
    tutor_client = ClientConfig(
        client_type="openai_chat_completions",
        api_key_var=args.api_key_env,
        api_base_url=args.base_url or "https://api.openai.com/v1",
    )

    env = load_environment(
        judge_client=env_client,
        judge_model=args.judge_model,
        student_client=env_client,
        student_model=args.student_model or args.judge_model,
        default_turns=args.default_turns,
        task_filter=args.task,
    )

    print(f"Loaded env: {type(env).__name__}")
    print(f"Dataset rows: {len(env.dataset)}")
    print(f"Tutor model: {args.tutor_model}")
    print("Running one rollout...\n")

    save_results = not args.no_save
    if save_results:
        if args.results_dir:
            results_path = Path(args.results_dir)
        else:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            task_slug = (args.task or "all").replace("/", "__")
            results_path = DEFAULT_RESULTS_ROOT / f"{ts}__{task_slug}__{args.tutor_model}"
        results_path.mkdir(parents=True, exist_ok=True)
    else:
        results_path = None

    outputs = await env.evaluate(
        client=tutor_client,
        model=args.tutor_model,
        num_examples=1,
        rollouts_per_example=1,
        state_columns=["judge_breakdown"],
        save_results=save_results,
        results_path=results_path,
    )
    _print_outputs(outputs)
    if results_path:
        print(f"\nResults saved to: {results_path}")
        for f in sorted(results_path.iterdir()):
            print(f"  {f.name}")


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
        print(f"Turns:   {info.get('turns')}")
        print(f"Materials length: {len(info['materials'])} chars")
        rubric = info.get("rubric") or []
        rubric_label = (
            f"{len(rubric)} criteria ({', '.join(c.get('id', '?') for c in rubric)})"
            if isinstance(rubric, list) else f"{len(rubric)} chars (legacy prose form)"
        )
        print(f"Rubric:           {rubric_label}")
        print(f"Tutor system prompt:   {len(info.get('tutor_system_prompt', ''))} chars")
        print(f"Student system prompt: {len(info.get('student_system_prompt', ''))} chars")
        print(f"Fixed student followups: {len(info.get('fixed_student_followups', []))}")
        print(f"Seed question (first 160 chars): {row['question'][:160]}...")

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
    rollouts = outputs.get("outputs", []) if isinstance(outputs, dict) else []
    if not rollouts:
        print(repr(outputs)[:2000])
        return
    r = rollouts[0]
    metrics = r.get("metrics", {}) or {}
    print(f"Reward (composite):  {r.get('reward', 0.0):.3f}")
    for k in ("transcript_score", "num_rubric_criteria", "num_turns"):
        if k in metrics:
            print(f"  {k:22s} {metrics[k]:.3f}")

    breakdown = r.get("judge_breakdown") or {}
    if isinstance(breakdown, dict) and breakdown.get("scores"):
        print("\nPer-criterion scores:")
        for criterion, score in breakdown["scores"].items():
            if score is None:
                print(f"  {criterion:22s} null (N/A — skipped from composite)")
            else:
                try:
                    print(f"  {criterion:22s} {float(score):.3f}")
                except (TypeError, ValueError):
                    print(f"  {criterion:22s} {score!r}")
        rationale = (breakdown.get("rationale") or "").strip()
        if rationale:
            print(f"\nJudge rationale: {rationale}")

    print(f"\nStop condition:      {r.get('stop_condition')}")
    print(f"Is completed:        {r.get('is_completed')}")
    completion = r.get("completion") or []
    if completion:
        print("\n--- Completion tail (last 3 turns) ---")
        for msg in completion[-3:]:
            role = _msg_field(msg, "role") or "?"
            content = _msg_field(msg, "content") or ""
            if isinstance(content, list):
                content = " ".join(str(p) for p in content)
            text = str(content).strip().replace("\n", "\n  ")
            print(f"[{role}] {text[:600]}{'...' if len(text) > 600 else ''}")


def _msg_field(msg: Any, name: str) -> Any:
    if isinstance(msg, dict):
        return msg.get(name)
    return getattr(msg, name, None)


if __name__ == "__main__":
    asyncio.run(main())
