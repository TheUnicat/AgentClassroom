"""LLM judge: scaffolding. Refactored from DEFAULT_RUBRIC entry of the same id.

Does the tutor *build* the explanation step-by-step rather than dumping
the answer? About structure of the lesson, not volume (anti_firehose) or
calibration (meeting_student_level). Over-Socratic interrogation when a
direct answer was wanted is also a scaffolding failure.
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.functions.llm._call import single_criterion_call
from teachingbench.grader.functions.llm._transcript import render_transcript


DESCRIPTION = (
    "Does the tutor *build* the explanation step-by-step rather than dumping the answer? "
    "Patterns that count as scaffolding: hints before answers, worked examples before "
    "abstractions, asking before telling (diagnostic questioning), checking-for-"
    "understanding before piling on, concrete-before-abstract, going from simple/concrete to very complex/abstract in a single message. The opposite is delivering "
    "a wholesale answer or starting from the most abstract framing. Note: scaffolding "
    "differs from anti-firehose (volume) and meeting_student_level (calibration) — it's "
    "about *structure* of the lesson, how it builds. Asking too many questions before "
    "answering when the student wanted a direct answer is also a scaffolding failure "
    "(over-Socratic)."
)

ANCHORS: list[dict[str, Any]] = [
    {"score": 1.0, "meaning": "Builds up from where the student is. Uses concrete examples to motivate abstract points. Asks targeted questions to elicit understanding. Knows when to direct-answer vs when to draw out."},
    {"score": 0.5, "meaning": "Some scaffolding but skips steps, jumps to abstraction very quickly, inappropriately large jumps in complexity, or over-Socratics when a direct answer was needed."},
    {"score": 0.0, "meaning": "No real scaffolding: drops the full answer wholesale or starts at the most abstract framing without setup or frequent messages that jump from simple to very abstract. Or: pure Socratic interrogation when the student wanted an answer."},
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
        criterion_id="scaffolding",
        description=DESCRIPTION,
        anchors=ANCHORS,
        materials=task_info.get("materials", "") or "",
        topic=task_info.get("topic", "") or "",
        transcript=render_transcript(messages),
        sampling_args=sampling_args,
    )


__all__ = ["score", "DESCRIPTION", "ANCHORS"]
