"""CLI: post-hoc re-judge a `results.jsonl` with any composer.

Usage:
    python -m teachingbench.grader.runner <results.jsonl> --composer v1_llm_only

For each row in the input file:
  - Load the composer module from `teachingbench.grader.composers`
  - Reconstruct the message list from `row["prompt"] + row["completion"]`
  - Call `composer.score(messages, info, ...)`
  - Write the breakdown under a NEW key `judge_breakdown__<composer.NAME>`.
    The original `judge_breakdown` is never overwritten — multiple
    composers' scores live side-by-side on the same row.

By default writes back in-place. Use `--out PATH` to write elsewhere.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("teachingbench.grader.runner")


def _load_composer(name: str):
    mod = importlib.import_module(f"teachingbench.grader.composers.{name}")
    if not hasattr(mod, "score"):
        raise ValueError(f"composer module `{name}` has no `score` function")
    return mod


def _build_messages(row: dict) -> list[dict]:
    msgs: list[dict] = []
    p = row.get("prompt")
    if isinstance(p, list):
        msgs.extend(p)
    c = row.get("completion")
    if isinstance(c, list):
        msgs.extend(c)
    return msgs


def _row_info(row: dict) -> dict:
    info = row.get("info") or {}
    if isinstance(info, str):
        try:
            return json.loads(info)
        except json.JSONDecodeError:
            return {}
    return info if isinstance(info, dict) else {}


def _build_judge_client(judge_model: str):
    """Build the appropriate provider client for `judge_model`."""
    from teachingbench.client_utils import detect_provider
    provider = detect_provider(judge_model)
    if provider == "anthropic":
        from anthropic import AsyncAnthropic
        return AsyncAnthropic()
    from openai import AsyncOpenAI
    return AsyncOpenAI()


async def _judge_row(composer, row: dict, *, judge_client, judge_model, sampling_args) -> dict:
    return await composer.score(
        _build_messages(row),
        _row_info(row),
        judge_client=judge_client,
        judge_model=judge_model,
        judge_sampling_args=sampling_args,
    )


async def main_async(args: argparse.Namespace) -> int:
    composer = _load_composer(args.composer)
    composer_name = getattr(composer, "NAME", args.composer)
    breakdown_key = f"judge_breakdown__{composer_name}"

    in_path = Path(args.results)
    if not in_path.exists():
        logger.error("input file not found: %s", in_path)
        return 1
    out_path = Path(args.out) if args.out else in_path

    judge_client = _build_judge_client(args.judge_model)
    sampling_args: dict[str, Any] = {"temperature": 0.2}

    rows: list[dict] = []
    with in_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))

    if args.limit is not None:
        rows_to_judge = rows[: args.limit]
    else:
        rows_to_judge = rows

    sem = asyncio.Semaphore(args.concurrency)

    async def one(i: int, row: dict) -> None:
        async with sem:
            if breakdown_key in row and not args.overwrite:
                logger.info("row %d: %s already present — skipping", i, breakdown_key)
                return
            try:
                row[breakdown_key] = await _judge_row(
                    composer, row,
                    judge_client=judge_client,
                    judge_model=args.judge_model,
                    sampling_args=sampling_args,
                )
                comp = row[breakdown_key].get("composite", 0.0)
                logger.info("row %d: composite=%.3f", i, comp)
            except Exception as e:
                logger.warning("row %d: judge failed: %s", i, e)
                row[breakdown_key] = {
                    "error": str(e), "composite": 0.0,
                    "scores": {}, "weights": {},
                }

    await asyncio.gather(*[one(i, r) for i, r in enumerate(rows_to_judge)])

    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(out_path)

    composites = [
        r[breakdown_key].get("composite", 0.0)
        for r in rows_to_judge
        if isinstance(r.get(breakdown_key), dict)
    ]
    mean = sum(composites) / len(composites) if composites else 0.0
    print(f"composer={composer_name}  rows={len(composites)}/{len(rows)}  "
          f"mean_composite={mean:.3f}  →  {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="teachingbench.grader.runner",
                                     description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("results", help="path to a results.jsonl file")
    parser.add_argument("--composer", "-c", required=True,
                        help="composer module name under teachingbench.grader.composers")
    parser.add_argument("--judge-model", "-m",
                        default=os.environ.get("TEACHINGBENCH_JUDGE_MODEL", "claude-opus-4-7"),
                        help="judge model id (default: $TEACHINGBENCH_JUDGE_MODEL or claude-opus-4-7)")
    parser.add_argument("--concurrency", "-j", type=int, default=4,
                        help="parallel judge calls (default 4)")
    parser.add_argument("--overwrite", action="store_true",
                        help="re-judge rows that already have judge_breakdown__<composer>")
    parser.add_argument("--limit", type=int, default=None,
                        help="judge only the first N rows (for sanity checks)")
    parser.add_argument("--out", help="output path (default: in-place)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
