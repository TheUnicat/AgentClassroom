"""Judge reliability check.

Replays an existing saved rollout's transcript through the judge LLM N times,
in parallel, and reports per-criterion + composite statistics. Useful for
distinguishing JUDGE noise from full-pipeline noise: if the same judge gives
wildly different scores to the exact same transcript, the rubric / prompt /
sampling needs tightening before any baseline numbers in D3 are trustworthy.

For full-pipeline noise (different student responses, different tutor seeds,
different judge calls all combined), see `task_reliability_check.py`.

Usage:
    python -m teachingbench.judge_reliability_check <run_id> [--n 8] [--judge-model gpt-5.4]

Where <run_id> is either:
    - a directory name under environments/teachingbench/outputs/runs/  (e.g.
      `20260510T143518Z__cs__intro_python_hello_world__gpt-5.4-nano`), or
    - an absolute / relative path to a results.jsonl file or its parent dir.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from teachingbench._reliability_helpers import print_reliability_table
from teachingbench.grader.judge import judge_transcript
from teachingbench.prompts import DEFAULT_RUBRIC

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNS_ROOT = REPO_ROOT / "environments" / "teachingbench" / "outputs" / "runs"


# --------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("run", help="Run directory name OR path to results.jsonl OR path to its parent dir.")
    p.add_argument("--n", type=int, default=8, help="Number of judge replays. Default: 8.")
    p.add_argument(
        "--judge-model",
        default=os.environ.get("DEFAULT_JUDGE_MODEL", "gpt-5.4"),
        help="Judge model (defaults to $DEFAULT_JUDGE_MODEL or gpt-5.4).",
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Judge sampling temperature. Default: 0.2 (matches TeachingRubric default).",
    )
    p.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help="Env var to read the OpenAI API key from.",
    )
    p.add_argument("--base-url", default=None, help="OpenAI-compatible base URL override.")
    p.add_argument(
        "--save",
        default=None,
        help="Optional path to write the per-trial scores as JSON (one record per trial).",
    )
    p.add_argument(
        "--use-current-rubric",
        action="store_true",
        help="Override the saved rubric with the current DEFAULT_RUBRIC from prompts.py. "
             "Useful when you've tightened the rubric after the rollout was saved.",
    )
    return p.parse_args()


# --------------------------------------------------------------------------


def resolve_results_path(arg: str) -> Path:
    """Accept either a bare run-id, a path to results.jsonl, or a path to a run dir."""
    p = Path(arg)
    if p.is_file() and p.name == "results.jsonl":
        return p
    if p.is_dir() and (p / "results.jsonl").is_file():
        return p / "results.jsonl"
    # bare run-id
    candidate = DEFAULT_RUNS_ROOT / arg / "results.jsonl"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"Could not locate results.jsonl from arg {arg!r}")


def load_rollout(results_path: Path) -> dict[str, Any]:
    """Read the (single) rollout record from results.jsonl, parse `info`, render transcript."""
    with results_path.open() as f:
        line = f.readline()
    if not line:
        raise ValueError(f"{results_path} is empty")
    rec = json.loads(line)

    info = rec.get("info") or {}
    if isinstance(info, str):
        try:
            info = json.loads(info)
        except json.JSONDecodeError:
            info = {}

    rubric = info.get("rubric")
    if not isinstance(rubric, list) or not rubric:
        rubric = DEFAULT_RUBRIC

    msgs: list[dict[str, Any]] = []
    for source in (rec.get("prompt") or []), (rec.get("completion") or []):
        for m in source:
            role = m.get("role") if isinstance(m, dict) else getattr(m, "role", "")
            content = m.get("content") if isinstance(m, dict) else getattr(m, "content", "")
            if isinstance(content, list):
                content = "\n".join(
                    p.get("text", "") if isinstance(p, dict) else str(getattr(p, "text", p)) for p in content
                )
            msgs.append({"role": str(role), "content": str(content or "")})

    transcript = _render_transcript(msgs)
    return {
        "task_id": info.get("task_id"),
        "topic": info.get("topic", ""),
        "materials": info.get("materials", ""),
        "rubric": rubric,
        "transcript": transcript,
        "original_reward": rec.get("reward"),
    }


def _render_transcript(msgs: list[dict[str, Any]]) -> str:
    """Same rendering as grader.judge._render_transcript (kept local to avoid private import)."""
    lines: list[str] = []
    for m in msgs:
        role = m.get("role", "")
        if role == "system":
            continue
        content = m.get("content", "")
        if role == "tool":
            lines.append(f"[Tool result]: {content}")
            continue
        speaker = "Tutor" if role == "assistant" else "Student"
        if content:
            lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


# --------------------------------------------------------------------------


async def run_trials(
    rollout: dict[str, Any], *, n: int, judge_client: AsyncOpenAI, judge_model: str, temperature: float
) -> list[dict[str, Any]]:
    """Run `n` independent judge calls in parallel against the same transcript."""
    print(f"Running {n} judge trials in parallel against {judge_model}…")
    tasks = [
        judge_transcript(
            judge_client,
            judge_model,
            rubric=rollout["rubric"],
            materials=rollout["materials"],
            topic=rollout["topic"],
            transcript=rollout["transcript"],
            sampling_args={"temperature": temperature},
        )
        for _ in range(n)
    ]
    results = await asyncio.gather(*tasks)
    return results


# --------------------------------------------------------------------------


def print_table(rollout: dict[str, Any], trials: list[dict[str, Any]], n: int) -> None:
    rubric = rollout["rubric"]
    criterion_ids = [c["id"] for c in rubric]
    composites = [t["composite"] for t in trials if "composite" in t]
    per_trial_scores = [t.get("scores", {}) for t in trials]
    errors = [t.get("error") for t in trials if t.get("error")]

    orig = rollout.get("original_reward")
    orig_line = (
        f"Original reward (from saved rollout): {orig:.3f}"
        if isinstance(orig, (int, float))
        else "Original reward: (n/a)"
    )
    print_reliability_table(
        title=f"Judge reliability — n={n}",
        context_lines=[
            f"Task:     {rollout['task_id']}",
            f"Topic:    {rollout['topic']}",
            orig_line,
        ],
        criterion_ids=criterion_ids,
        per_trial_scores=per_trial_scores,
        per_trial_composites=composites,
        n=n,
        errors=errors,
    )


# --------------------------------------------------------------------------


async def main() -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Quiet down the HTTPX/openai/anthropic chatter, keep our own INFO logs.
    for noisy in ("httpx", "openai", "anthropic", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    from teachingbench.client_utils import detect_provider
    args = parse_args()

    # Decide which provider's client to build based on judge model name.
    provider = detect_provider(args.judge_model)
    if provider == "anthropic":
        from anthropic import AsyncAnthropic
        anth_key = os.environ.get("ANTHROPIC_API_KEY")
        if not anth_key:
            raise SystemExit("$ANTHROPIC_API_KEY is not set (needed for claude-* judge)")
        judge_client = AsyncAnthropic(api_key=anth_key)
        print(f"Using Anthropic judge client for model: {args.judge_model}")
    else:
        api_key = os.environ.get(args.api_key_env)
        if not api_key:
            raise SystemExit(f"${args.api_key_env} is not set")
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if args.base_url:
            client_kwargs["base_url"] = args.base_url
        judge_client = AsyncOpenAI(**client_kwargs)
        print(f"Using OpenAI judge client for model: {args.judge_model}")

    results_path = resolve_results_path(args.run)
    print(f"Loading rollout from: {results_path}")
    rollout = load_rollout(results_path)
    if args.use_current_rubric:
        rollout["rubric"] = DEFAULT_RUBRIC
        print("Using CURRENT DEFAULT_RUBRIC (overriding saved rubric).")
    print(f"Task: {rollout['task_id']}  Topic: {rollout['topic']}  "
          f"Rubric: {[c['id'] for c in rollout['rubric']]}  "
          f"Transcript chars: {len(rollout['transcript'])}")

    trials = await run_trials(
        rollout,
        n=args.n,
        judge_client=judge_client,
        judge_model=args.judge_model,
        temperature=args.temperature,
    )

    print_table(rollout, trials, args.n)

    if args.save:
        out_path = Path(args.save)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as f:
            for t in trials:
                f.write(json.dumps(t) + "\n")
        print(f"\nPer-trial scores written to: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
