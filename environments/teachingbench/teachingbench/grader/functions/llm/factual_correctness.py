"""LLM judge: factual_correctness. Refactored from DEFAULT_RUBRIC entry of the same id.

Two distinct failure modes the judge keeps separate when scoring:
(a) Blatant misinformation — confidently wrong claims, hallucinated
references, broken proofs, code that doesn't do what the tutor claims.
(b) Misleading without strictly lying — every individual claim defensible
but the overall picture is wrong (unflagged oversimplification, omitted
caveats, slanted framing).
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.functions.llm._call import single_criterion_call
from teachingbench.grader.functions.llm._transcript import render_transcript


DESCRIPTION = (
    "Are the tutor's technical claims correct, AND does the overall picture they paint "
    "avoid being misleading? Two distinct failure modes to keep separate when scoring: "
    "(a) **Blatant misinformation** — confidently asserting wrong things. Wrong "
    "definitions, hallucinated theorems / papers / documentation references, broken "
    "proofs presented as valid, code that doesn't do what the tutor claims, made-up "
    "facts. The student will internalize false claims. Score at or near 0. "
    "(b) **Misleading without strictly lying** — every individual claim could be "
    "defended as technically accurate, but the overall impression conveyed is wrong. "
    "Oversimplification presented as the full picture (without flagging it as a "
    "simplification), omitted critical caveats or conditions, framing that nudges the "
    "student toward a wrong inference, or a true-but-unrepresentative example used to "
    "make a general point. Score around 0.3."
    "Honest hedging when uncertain (\"I'm not 100% sure but…\") is fine and does not "
    "penalize. Flagging an oversimplification (\"this is a simplification — the full "
    "story involves...\") is not penalized, either. Not flagging an oversimplification would be "
    "correct-with-minor-issue (0.75)."
)

ANCHORS: list[dict[str, Any]] = [
    {"score": 1.0, "meaning": "All technical claims are correct. Any uncertainty is acknowledged when present."},
    {"score": 0.7, "meaning": "Mostly correct, with a non-load-bearing minor error or an oversimplification — small enough that it doesn't materially mislead the student."},
    {"score": 0.3, "meaning": "Misleading without strictly lying. Every individual claim could be defended as technically true, but the impression the student walks away with is wrong: critical caveats omitted, oversimplification presented as the full picture without flagging, slanted framing, or an unrepresentative example used to make a general point."},
    {"score": 0.0, "meaning": "Blatant misinformation. Wrong definitions stated confidently, hallucinated theorem / paper / documentation references, broken proofs presented as valid, code that doesn't do what the tutor claims, made-up facts. The student will internalize false claims."},
]


async def score(
    messages: list[dict],
    task_info: dict,
    *,
    judge_client: Any,
    judge_model: str,
    sampling_args: dict[str, Any] | None = None,
) -> dict:
    return await single_criterion_call(
        judge_client,
        judge_model,
        criterion_id="factual_correctness",
        description=DESCRIPTION,
        anchors=ANCHORS,
        materials=task_info.get("materials", "") or "",
        topic=task_info.get("topic", "") or "",
        transcript=render_transcript(messages),
        sampling_args=sampling_args,
    )


__all__ = ["score", "DESCRIPTION", "ANCHORS"]
