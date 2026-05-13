"""LLM judge: anti_firehose. Refactored from DEFAULT_RUBRIC entry of the same id.

The single most common failure mode for AI tutors: information dumps,
listicles in the first message, enumerating five options when one was
needed, tangential additions, preview-of-next-lesson endings.

Note: in v2_hybrid this criterion is typically replaced by the deterministic
`anti_firehose_length` function. The LLM version is kept for v1 parity and
as a fallback for composers that prefer semantic judgment over a length
proxy.
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.functions.llm._call import single_criterion_call
from teachingbench.grader.functions.llm._transcript import render_transcript


DESCRIPTION = (
    "Did the tutor avoid information dumps? Specific patterns that count as firehosing: "
    "(a) listicle/bulleted/sectioned responses in conversational chat (especially in the "
    "FIRST message — a listicle or long turn 1 is a strong signal), (b) consistently >100 words "
    "per message without a good reason (long necessary code snippets and student-requested "
    "long content excepted), (c) enumerating 5 possible causes/options when one or two "
    "was needed, (d) tangential additions (\"by the way you can also…\"), (e) "
    "preview-of-next-lesson endings, (f) multiple unrelated concepts in one message. "
    "(g) Excessive examples–frequently creating new, lengthy examples or analogies that overwhelm "
    "(h) Repeating the same information frequently (\"Once again, this circles back to idea..\") when unnecessary AND student does not engage with it. "
    "Anti-firehose ideal: short focused messages that respond to what the student said, "
    "leaving room for the student to lead. This is the most common failure "
    "mode for AI tutors and is weighted accordingly."
)

ANCHORS: list[dict[str, Any]] = [
    {"score": 1.0, "meaning": "Tight throughout. One concept per message, conversational length, no unprompted tangents, no preview-of-next-lesson endings. The tutor reacts to what the student specifically said."},
    {"score": 0.5, "meaning": "Mostly tight but with one notable firehose pattern: an over-long response, multiple unprompted tangents, or one or two sectioned/bulleted message where prose would have served better."},
    {"score": 0.3, "meaning": "Inappropriate listicle/sectioned response in several messages OR consistently >100 words per message without clear reason OR often enumerates many options when one was needed OR frequent verbose repetition. Anchor here for any of these patterns."},
    {"score": 0.0, "meaning": "Pervasive firehose: many firehose patterns, multiple messages are wall-of-text dumps with structured lists, alternative approaches, tangents, new complex examples, preview-of-next-lesson. Reads like a textbook chapter, not a chat."},
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
        criterion_id="anti_firehose",
        description=DESCRIPTION,
        anchors=ANCHORS,
        materials=task_info.get("materials", "") or "",
        topic=task_info.get("topic", "") or "",
        transcript=render_transcript(messages),
        sampling_args=sampling_args,
    )


__all__ = ["score", "DESCRIPTION", "ANCHORS"]
