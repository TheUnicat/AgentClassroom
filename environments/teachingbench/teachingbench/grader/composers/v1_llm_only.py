"""v1_llm_only: the LLM-only baseline composer.

Wraps the existing `judge_transcript` (the current TeachingRubric judge)
inside the new composer interface. No behavior change: same rubric, same
prompt, same provider dispatch, same composite formula. On a given rollout
this reproduces the scores in `judge_breakdown` within LLM sampling noise.

The rubric is taken from `task_info["rubric"]` per-task, or `DEFAULT_RUBRIC`.
Weights come from each criterion's `weight` field on the rubric, or uniform
1/N — same as the v1 in-line judge.
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.judge import judge_transcript
from teachingbench.prompts import DEFAULT_RUBRIC

NAME = "v1_llm_only"

# v1 reads weights from the rubric itself (criterion.weight or uniform 1/N),
# so this dict stays empty as a convention marker.
WEIGHTS: dict[str, float] = {}


async def score(
    messages: list[dict],
    task_info: dict,
    *,
    judge_client: Any,
    judge_model: str,
    judge_sampling_args: dict[str, Any] | None = None,
) -> dict:
    rubric = task_info.get("rubric")
    if not isinstance(rubric, list) or not rubric:
        rubric = DEFAULT_RUBRIC
    return await judge_transcript(
        judge_client,
        judge_model,
        rubric=rubric,
        materials=task_info.get("materials", "") or "",
        topic=task_info.get("topic", "") or "",
        transcript=_render_transcript(messages),
        sampling_args=judge_sampling_args,
    )


def _render_transcript(messages: list[dict]) -> str:
    """Render a Tutor:/Student: transcript from a flat message list.

    Mirrors `grader.judge._render_transcript` but takes the already-combined
    list (since post-hoc judging reads prompt+completion from a results.jsonl
    row, not the live env state).
    """
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "") if isinstance(m, dict) else getattr(m, "role", "")
        if role == "system":
            continue
        content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
        if isinstance(content, list):
            content = "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(getattr(part, "text", ""))
                for part in content
            )
        content = str(content or "")
        if role == "tool":
            lines.append(f"[Tool result]: {content}")
            continue
        if not content:
            continue
        speaker = "Tutor" if role == "assistant" else "Student"
        lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)
