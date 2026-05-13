"""LLM judge: bridging. Refactored from DEFAULT_RUBRIC entry of the same id.

When the student has shared concrete materials or context, does the tutor
build on those specifics rather than delivering a generic explainer? N/A
(null) when the student has not shared anything bridgeable — a vague
"teach me Python from scratch" does NOT count as bridgeable context.
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.functions.llm._call import single_criterion_call
from teachingbench.grader.functions.llm._transcript import render_transcript


DESCRIPTION = (
    "When the student has shared materials or stated specific context (pasted slides, "
    "their code, a traceback, a homework page, an excerpt of their notes), does the tutor "
    "*build on* those specifics — referencing them, pointing at the relevant parts, using "
    "the student's own examples as the bridge? A failure is delivering a generic explainer "
    "that ignores what the student shared. Return null if the student has not shared "
    "specific materials or context — a vague \"teach me Python from scratch\" does NOT "
    "count as bridgeable context."
)

ANCHORS: list[dict[str, Any]] = [
    {"score": None, "meaning": "Student has not shared any materials or specific context. Criterion N/A — return null."},
    {"score": 1.0, "meaning": "Tutor explicitly references the student's materials/context, points at specific parts, builds the explanation on them, and uses the student's own examples or words."},
    {"score": 0.4, "meaning": "Tutor mentions the materials in passing but the actual content is generic — could be lifted into any tutorial without losing much."},
    {"score": 0.0, "meaning": "Generic explainer that ignores or contradicts what the student shared. Could have been written without seeing the student's specifics. Response is inappropriate for the student's circumstances."},
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
        criterion_id="bridging",
        description=DESCRIPTION,
        anchors=ANCHORS,
        materials=task_info.get("materials", "") or "",
        topic=task_info.get("topic", "") or "",
        transcript=render_transcript(messages),
        sampling_args=sampling_args,
    )


__all__ = ["score", "DESCRIPTION", "ANCHORS"]
