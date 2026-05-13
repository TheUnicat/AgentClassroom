"""GradingEnv — single-turn rubric grading.

Each rollout shows the grader model one piece of student work + a rubric, and asks for a
single integer grade on the 1-4 scale plus a short rationale. The reward function
compares the model's grade to the ground-truth human grade. No multi-turn dialog, no
tool calls, no env_response loop — this is a `vf.SingleTurnEnv`.

Mirror of `teachingbench/env.py` structure: `load_environment` constructs the rubric,
dataset, and env. Provider-aware structured-output dispatch lives in
`grader/agreement.py` (sibling of `teachingbench/grader/judge.py`).
"""

from __future__ import annotations

import logging
from typing import Any

import verifiers as vf
from openai import AsyncOpenAI

from gradingbench.dataset import load_dataset
from gradingbench.grader.agreement import GradingRubric
from gradingbench.prompts import DEFAULT_GRADER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def load_environment(
    num_examples: int | None = None,
    judge_model: str = "gpt-5.4-nano",
    judge_client: AsyncOpenAI | None = None,
    system_prompt: str | None = None,
    **kwargs: Any,
) -> vf.Environment:
    """Verifiers entry point. Returns a `vf.SingleTurnEnv` wired with the dataset, the
    default grader system prompt, and a `GradingRubric` that scores the grader's
    predicted grade against the ground truth via agreement.

    `judge_client` / `judge_model` are kept for sibling-API parity with teachingbench;
    the agreement reward is deterministic (no judge LLM call) but the parameters are
    threaded through so a future inter-rater study can swap in a judge variant
    without changing the entry-point signature.
    """
    if judge_client is None:
        judge_client = AsyncOpenAI()

    rubric = GradingRubric(
        judge_client=judge_client,
        judge_model=judge_model,
    )
    dataset = load_dataset(num_examples=num_examples)
    return vf.SingleTurnEnv(
        dataset=dataset,
        rubric=rubric,
        system_prompt=system_prompt if system_prompt is not None else DEFAULT_GRADER_SYSTEM_PROMPT,
        **kwargs,
    )
