"""LLM judge: answers_the_question. Refactored from DEFAULT_RUBRIC entry of the same id.

Did the tutor actually converge on the student's specific ask, or did the
conversation pivot to an adjacent topic, get stuck in clarifying loops, or
trail off without ever reaching the substance? A brief clarifying question
on a genuinely ambiguous ask is correct and not penalized here.
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.functions.llm._call import single_criterion_call
from teachingbench.grader.functions.llm._transcript import render_transcript


DESCRIPTION = (
    "Did the tutor actually answer the student's question? The student arrived with a "
    "specific ask — an explanation, a hint, a check on their work, a roadmap. The tutor "
    "should converge on that ask. Failure modes: pivoting to a related but different "
    "topic, asking endless clarifying questions when none were needed, refusing to commit "
    "to a clear answer when one exists, or trailing off without ever getting to the "
    "substance. Note: if the student's ask is genuinely ambiguous, a brief clarifying "
    "question is correct — that's not a failure of this criterion."
)

ANCHORS: list[dict[str, Any]] = [
    {"score": 1.0, "meaning": "Directly addresses what was asked. The conversation reaches a clear, substantive answer to the student's actual question."},
    {"score": 0.4, "meaning": "Partially addresses the question, but meanders, addresses an adjacent question, excessive tangents, or only gets to the substance in the last turn."},
    {"score": 0.0, "meaning": "Avoids the question, gets pulled off into a different topic, refuses to commit, or never reaches the substance."},
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
        criterion_id="answers_the_question",
        description=DESCRIPTION,
        anchors=ANCHORS,
        materials=task_info.get("materials", "") or "",
        topic=task_info.get("topic", "") or "",
        transcript=render_transcript(messages),
        sampling_args=sampling_args,
    )


__all__ = ["score", "DESCRIPTION", "ANCHORS"]
