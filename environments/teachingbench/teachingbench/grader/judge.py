"""TeachingRubric — subclass of `vf.JudgeRubric` (PI's canonical LLM-judge format).

Reward funcs read from `state["reward_breakdown"]`, populated by `TeachingEnv.env_response`
when the dialog terminates. The composite is the headline reward (weight 1.0); sub-scores
are zero-weight metrics so they show up in the Prime dashboard alongside.

The `JudgeRubric` parent owns the judge client/model — TeachingEnv reuses
`rubric.judge_client` / `rubric.judge_model` for quiz generation and free-response judging
so there's a single source of truth for "the env-side LLM."
"""

from __future__ import annotations

from typing import Any

import verifiers as vf
from openai import AsyncOpenAI

DEFAULT_TEACHING_JUDGE_PROMPT = (
    "Question: {question}\n\nAnswer key: {answer}\n\nResponse: {response}\n\n"
    'Reply "yes" or "no" only.'
)


class TeachingRubric(vf.JudgeRubric):
    def __init__(
        self,
        judge_client: AsyncOpenAI | None = None,
        judge_model: str = "gpt-4.1-nano",
        judge_sampling_args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            judge_client=judge_client,
            judge_model=judge_model,
            judge_prompt=DEFAULT_TEACHING_JUDGE_PROMPT,
            judge_sampling_args=judge_sampling_args,
            **kwargs,
        )
        self.add_reward_func(_composite_reward, weight=1.0)
        self.add_metric(_quiz_score)
        self.add_metric(_self_rating_score)
        self.add_metric(_num_quiz_items)


def _breakdown(state: Any) -> dict[str, Any]:
    if isinstance(state, dict):
        b = state.get("reward_breakdown")
    else:
        b = getattr(state, "reward_breakdown", None)
    return b if isinstance(b, dict) else {}


async def _composite_reward(state: Any, **_: Any) -> float:
    return float(_breakdown(state).get("composite", 0.0))


async def _quiz_score(state: Any, **_: Any) -> float:
    return float(_breakdown(state).get("quiz_score", 0.0))


async def _self_rating_score(state: Any, **_: Any) -> float:
    return float(_breakdown(state).get("self_rating_score", 0.0))


async def _num_quiz_items(state: Any, **_: Any) -> float:
    items = _breakdown(state).get("per_item")
    return float(len(items) if isinstance(items, list) else 0)


# Stable __name__ values so they show up cleanly in Prime metrics.
_composite_reward.__name__ = "composite"
_quiz_score.__name__ = "quiz_score"
_self_rating_score.__name__ = "self_rating_score"
_num_quiz_items.__name__ = "num_quiz_items"
