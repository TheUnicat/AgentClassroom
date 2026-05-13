"""LLM judge: clarity. Refactored from DEFAULT_RUBRIC entry of the same id.

Independent of length and student level: is the writing itself clear?
Sentences parse on first read, jargon is introduced before use, no
unexplained logical jumps. Equally bad: being too terse for the thing
being explained so the student has to back-fill skipped steps.
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.functions.llm._call import single_criterion_call
from teachingbench.grader.functions.llm._transcript import render_transcript


DESCRIPTION = (
    "Independent of message length and student level: is the writing itself clear? "
    "Sentences parse on first read. Technical terms are introduced before being used. No "
    "unexplained logical jumps within a single explanation. No sentences that try to do "
    "five things at once. No jargon used as if defined when it wasn't. Equally bad: "
    "being too terse for the specific thing being explained, such that the student has "
    "to back-fill steps the tutor skipped. Note: clarity is about *writing*, not about "
    "*level* (which is meeting_student_level) or *length* (which is anti_firehose)."
    "Tip: checking to see if the student was confused can help with grading here"
)

ANCHORS: list[dict[str, Any]] = [
    {"score": 1.0, "meaning": "Clean, readable. Each explanation builds smoothly — no unexplained leaps, no tangled sentences, jargon introduced before use."},
    {"score": 0.5, "meaning": "One or two confusing passages: a large logical jump, a few sentences that requires re-reading, more than one term used before being introduced."},
    {"score": 0.0, "meaning": "Repeatedly hard to follow. Tangled sentences, frequent logical leaps, jargon used as if already defined, or so terse that the student has to fill in missing steps."},
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
        criterion_id="clarity",
        description=DESCRIPTION,
        anchors=ANCHORS,
        materials=task_info.get("materials", "") or "",
        topic=task_info.get("topic", "") or "",
        transcript=render_transcript(messages),
        sampling_args=sampling_args,
    )


__all__ = ["score", "DESCRIPTION", "ANCHORS"]
