"""LLM judge: meeting_student_level. Refactored from DEFAULT_RUBRIC entry of the same id.

Does the tutor calibrate to the student's actual level? Two-sided failure
mode: too advanced (using concepts the student disclaimed knowing) or too
elementary (re-explaining things the student already knows). Includes
following the student's redirects ("just show me B").
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.functions.llm._call import single_criterion_call
from teachingbench.grader.functions.llm._transcript import render_transcript


DESCRIPTION = (
    "Does the tutor calibrate to the student's actual level? Read the student's messages "
    "FIRST to determine what they know and don't know (their stated background, "
    "vocabulary, kinds of mistakes, what they say they don't understand). THEN evaluate "
    "whether the tutor pitches at that level. Two-sided failure mode: (a) too advanced — "
    "explaining basic things using concepts the student has already disclaimed knowing, "
    "citing theorems above their level repeatedly, especially after the student said they "
    "don't follow; (b) too elementary — re-explaining things the student demonstrated they "
    "know, treating an expert as a beginner. Also includes following the student's "
    "redirects (\"i don't need version A, just show me B\"). "
    "Tip: checking to see if the student was confused can help with grading here. "
    "Tip: Think about what the student's knowledge of the subject could be based on their messages"
)

ANCHORS: list[dict[str, Any]] = [
    {"score": 1.0, "meaning": "Consistently pitches at the student's stated/demonstrated level. Uses analogies appropriate to their background. Doesn't waste time on things they already know. Respects redirects."},
    {"score": 0.6, "meaning": "Starts at the wrong level (too advanced or too elementary) but adjusts within one or two messages after student feedback. Student sometimes confused."},
    {"score": 0.3, "meaning": "Inconsistent calibration throughout — frequently over- or under-explains. Student often confused and learning is slowed."},
    {"score": 0.0, "meaning": "Cites concepts above the student's stated level *repeatedly*, even after the student said they don't understand (or the converse); explains advanced things using more advanced things. Or: ignores explicit redirects and continues at the wrong level."},
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
        criterion_id="meeting_student_level",
        description=DESCRIPTION,
        anchors=ANCHORS,
        materials=task_info.get("materials", "") or "",
        topic=task_info.get("topic", "") or "",
        transcript=render_transcript(messages),
        sampling_args=sampling_args,
    )


__all__ = ["score", "DESCRIPTION", "ANCHORS"]
