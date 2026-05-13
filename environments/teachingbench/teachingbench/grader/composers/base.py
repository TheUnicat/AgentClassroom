"""Composer protocol + default formula wrapper.

A composer picks a set of judge functions, assigns weights, and combines
their outputs into a single composite score. Each composer is its own
file under `grader/composers/`.

Composer module contract:
    NAME:    str                       — short id, written as `judge_breakdown__<NAME>`
    WEIGHTS: dict[str, float]          — per-function weight (must sum > 0)
    async def score(messages, task_info, *, judge_client=None,
                    judge_model=None, judge_sampling_args=None) -> dict
        Returns a `judge_breakdown` dict (see `default_compose` for shape).

The default composite math (`default_compose`) routes through
`reward_scoring.compute_composite` — the convex-revquad-ceilings v3 formula.
A composer can override by computing the composite locally; the equation
belongs next to the weights that drive it.
"""

from __future__ import annotations

from typing import Any, Protocol

from teachingbench.grader.reward_scoring import compute_composite, describe as describe_formula


class Composer(Protocol):
    NAME: str
    WEIGHTS: dict[str, float]

    async def score(
        self,
        messages: list[dict],
        task_info: dict,
        *,
        judge_client: Any = None,
        judge_model: str | None = None,
        judge_sampling_args: dict[str, Any] | None = None,
    ) -> dict: ...


def default_compose(
    scores: dict[str, float | None],
    weights: dict[str, float],
    *,
    rationale: str = "",
    rubric: list[dict] | None = None,
    extra_terms: dict[str, Any] | None = None,
) -> dict:
    """Standard composer return shape using the default reward_scoring formula.

    Composers that don't need custom math should call this. Returns the
    same `judge_breakdown` dict shape v1 has emitted since the dashboard
    started consuming it: scores / weights / rationale / composite /
    composite_raw / composite_terms / formula / rubric.
    """
    result = compute_composite(scores, weights)
    terms = dict(result["terms"])
    if extra_terms:
        terms.update(extra_terms)
    return {
        "scores": scores,
        "weights": weights,
        "rationale": rationale,
        "composite": result["composite"],
        "composite_raw": result["composite_raw"],
        "composite_terms": terms,
        "formula": describe_formula(),
        "rubric": rubric or [],
    }


__all__ = ["Composer", "default_compose"]
