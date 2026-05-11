"""Inter-task variance check.

Runs ONE fresh rollout for each of N different tasks and reports the
composite distribution across them. Answers: *does the eval actually
discriminate between tasks, or is every rollout converging to ~the same
score regardless of difficulty / category?*

Distinct from `task_reliability_check.py` (which runs n rollouts of the
SAME task) and `judge_reliability_check.py` (which re-judges ONE saved
transcript n times). Use this when calibrating the rubric / judge on a
new model, or sanity-checking that ceilings aren't pinning every task
to the same number.

Usage:
    python -m teachingbench.inter_task_check \\
        --task-ids cs/big_o_notation math/derivative_what_it_measures \\
                   cs/halting_problem cs/python_keyerror_dict \\
                   math/spivak_x_i_exponent_or_index \\
        --tutor-model gpt-5.4-mini
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from verifiers.types import ClientConfig

from teachingbench.env import load_environment


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--task-ids", required=True, nargs="+", help="Space-separated list of task IDs.")
    p.add_argument("--tutor-model", required=True, help="Tutor model (the model under test).")
    p.add_argument("--student-model", default=None, help="Defaults to --judge-model.")
    p.add_argument(
        "--judge-model",
        default=os.environ.get("DEFAULT_JUDGE_MODEL", "gpt-5.4"),
        help="Judge model. Default: $DEFAULT_JUDGE_MODEL or gpt-5.4.",
    )
    p.add_argument("--api-key-env", default="OPENAI_API_KEY")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL override.")
    p.add_argument("--save", default=None, help="Optional JSON path to dump per-task results.")
    p.add_argument(
        "--sequential", action="store_true",
        help="Run tasks one at a time instead of in parallel. Slower but easier to debug.",
    )
    return p.parse_args()


async def run_one_task(
    task_id: str,
    *,
    tutor_client: ClientConfig,
    tutor_model: str,
    env_client: AsyncOpenAI,
    student_model: str,
    judge_model: str,
) -> dict[str, Any]:
    env = load_environment(
        judge_client=env_client,
        judge_model=judge_model,
        student_client=env_client,
        student_model=student_model,
        task_filter=task_id,
    )
    outputs = await env.evaluate(
        client=tutor_client,
        model=tutor_model,
        num_examples=1,
        rollouts_per_example=1,
        state_columns=["judge_breakdown"],
        save_results=False,
    )
    rollouts = outputs.get("outputs", []) if isinstance(outputs, dict) else []
    if not rollouts:
        return {"task_id": task_id, "composite": None, "error": "no rollout produced"}
    r = rollouts[0]
    breakdown = r.get("judge_breakdown") or {}
    return {
        "task_id": task_id,
        "composite": float(r.get("reward", 0.0)),
        "scores": (breakdown.get("scores") or {}),
        "weights": (breakdown.get("weights") or {}),
        "per_criterion_ceiling": (breakdown.get("composite_terms") or {}).get("per_criterion_ceiling") or {},
        "convex_base": (breakdown.get("composite_terms") or {}).get("convex_base"),
        "composite_ceiling": (breakdown.get("composite_terms") or {}).get("composite_ceiling"),
        "stop_condition": r.get("stop_condition"),
    }


async def main() -> None:
    args = parse_args()
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"${args.api_key_env} is not set")

    base_url = args.base_url or "https://api.openai.com/v1"
    env_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    tutor_client = ClientConfig(
        client_type="openai_chat_completions",
        api_key_var=args.api_key_env,
        api_base_url=base_url,
    )
    student_model = args.student_model or args.judge_model

    print(
        f"Running {len(args.task_ids)} task(s) (one rollout each)\n"
        f"  tutor={args.tutor_model}  student={student_model}  judge={args.judge_model}\n"
        f"  parallel={not args.sequential}"
    )

    coros = [
        run_one_task(
            t,
            tutor_client=tutor_client,
            tutor_model=args.tutor_model,
            env_client=env_client,
            student_model=student_model,
            judge_model=args.judge_model,
        )
        for t in args.task_ids
    ]
    if args.sequential:
        results: list[dict[str, Any]] = []
        for c in coros:
            results.append(await c)
    else:
        results = await asyncio.gather(*coros)

    _print_table(results)

    if args.save:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            json.dump(results, f, indent=2)
        print(f"\nSaved per-task results to: {out_path}")


def _print_table(results: list[dict[str, Any]]) -> None:
    print(f"\n=== Inter-task variance — n={len(results)} ===\n")
    print(f"{'task':45s} {'composite':>9s}   {'binding ceiling (criterion @ value)':50s}")
    print("-" * 110)
    composites: list[float] = []
    errors: list[str] = []
    for r in results:
        if r.get("error"):
            errors.append(f"{r['task_id']}: {r['error']}")
            continue
        c = r.get("composite")
        if c is None:
            errors.append(f"{r['task_id']}: no composite")
            continue
        composites.append(c)
        pcc = r.get("per_criterion_ceiling") or {}
        binding = min(pcc.items(), key=lambda x: x[1]) if pcc else None
        bind_str = f"{binding[0]} @ {binding[1]:.3f}" if binding else "—"
        print(f"{r['task_id']:45s} {c:>9.4f}   {bind_str:50s}")

    print("-" * 110)
    if composites:
        mean = statistics.mean(composites)
        stdev = statistics.stdev(composites) if len(composites) > 1 else 0.0
        cv = stdev / mean if mean > 0 else 0.0
        print(f"{'mean':45s} {mean:>9.4f}")
        print(f"{'stdev':45s} {stdev:>9.4f}")
        print(f"{'CV':45s} {cv:>9.4f}")
        print(f"{'range':45s} {max(composites) - min(composites):>9.4f}")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  {e}")

    print(
        "\nInterpretation:\n"
        "  Cross-task CV measures how much the eval *discriminates* between tasks.\n"
        "  Higher CV here = good (the rubric is responsive to task differences).\n"
        "  Very low CV (e.g. <0.05) across diverse tasks = warning sign — the\n"
        "  rubric / ceilings may be pinning everything to the same number."
    )


if __name__ == "__main__":
    asyncio.run(main())
