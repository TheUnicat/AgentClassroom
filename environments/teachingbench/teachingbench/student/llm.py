"""LLM-backed student. Uses any AsyncOpenAI-compatible client."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from teachingbench.prompts import (
    STUDENT_QUIZ_SYSTEM_PROMPT,
    STUDENT_SELF_RATE_SYSTEM_PROMPT,
    STUDENT_SYSTEM_PROMPT,
)
from teachingbench.student.base import AskDecision, SelfRating

logger = logging.getLogger(__name__)


class LLMStudent:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        *,
        sampling_args: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.sampling_args = sampling_args or {"temperature": 0.7}

    async def decide(
        self,
        messages: list[dict[str, Any]],
        *,
        topic: str,
        materials: str,
    ) -> AskDecision:
        system = {"role": "system", "content": STUDENT_SYSTEM_PROMPT.format(topic=topic, materials=materials)}
        # Re-frame: the tutor's messages become "tutor" content the student reads.
        # We keep verifiers' role labels but flip context so the student sees the dialog.
        history = _flip_for_student(messages)
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[system] + history,
            **self.sampling_args,
        )
        raw = resp.choices[0].message.content or ""
        decision = _parse_json(raw, default={"action": "ready", "question": None})
        if decision.get("action") not in ("follow_up", "ready"):
            decision = {"action": "ready", "question": None}
        if decision["action"] == "follow_up" and not decision.get("question"):
            decision = {"action": "ready", "question": None}
        return decision  # type: ignore[return-value]

    async def answer_quiz(
        self,
        quiz: list[dict[str, Any]],
        *,
        topic: str,
        teaching_trace: list[dict[str, Any]],
    ) -> list[Any]:
        system = {"role": "system", "content": STUDENT_QUIZ_SYSTEM_PROMPT.format(topic=topic)}
        trace_text = _trace_to_text(teaching_trace)
        answers: list[Any] = []
        for item in quiz:
            prompt = _quiz_item_prompt(item, trace_text)
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[system, {"role": "user", "content": prompt}],
                **self.sampling_args,
            )
            raw = resp.choices[0].message.content or ""
            parsed = _parse_quiz_answer(raw, item)
            answers.append(parsed)
        return answers

    async def self_rate(self, *, topic: str) -> SelfRating:
        system = {"role": "system", "content": STUDENT_SELF_RATE_SYSTEM_PROMPT.format(topic=topic)}
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[system, {"role": "user", "content": "Self-rate now."}],
            **self.sampling_args,
        )
        raw = resp.choices[0].message.content or ""
        rating = _parse_json(raw, default={})
        return {
            "clarity": _clamp_int(rating.get("clarity"), 1, 5, default=3),
            "coverage": _clamp_int(rating.get("coverage"), 1, 5, default=3),
            "confidence": _clamp_int(rating.get("confidence"), 1, 5, default=3),
            "still_confusing": str(rating.get("still_confusing", "") or ""),
        }


def _flip_for_student(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The tutor was 'assistant' from verifiers' POV; the student sees them as the speaker.

    Drop the original system prompt and the seed user message context. Render the
    rest as a transcript the student is reacting to.
    """
    transcript_lines: list[str] = []
    for msg in messages:
        role = _role(msg)
        content = _content(msg)
        if role == "system":
            continue
        speaker = "Tutor" if role == "assistant" else "You"
        if content:
            transcript_lines.append(f"{speaker}: {content}")
    transcript = "\n\n".join(transcript_lines)
    return [{"role": "user", "content": transcript or "(no dialog yet)"}]


def _trace_to_text(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in messages:
        role = _role(msg)
        if role == "system":
            continue
        speaker = "Tutor" if role == "assistant" else "Student"
        content = _content(msg)
        if content:
            lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


def _quiz_item_prompt(item: dict[str, Any], trace_text: str) -> str:
    if item.get("type") == "mcq":
        opts = "\n".join(f"  {chr(65 + i)}. {opt}" for i, opt in enumerate(item.get("options", [])))
        return (
            f"Tutoring trace:\n{trace_text}\n\n"
            f"Question: {item['question']}\n{opts}\n\n"
            'Reply with JSON: {"answer": "A" | "B" | "C" | "D"}'
        )
    return (
        f"Tutoring trace:\n{trace_text}\n\n"
        f"Question: {item['question']}\n\n"
        'Reply with JSON: {"answer": "<your answer>"}'
    )


def _parse_quiz_answer(raw: str, item: dict[str, Any]) -> Any:
    parsed = _parse_json(raw, default={})
    return parsed.get("answer", "")


def _parse_json(raw: str, *, default: Any) -> Any:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract the first {...} block
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse JSON from student response: %r", raw[:200])
        return default


def _clamp_int(v: Any, lo: int, hi: int, *, default: int) -> int:
    try:
        i = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, i))


def _role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    return str(getattr(msg, "role", ""))


def _content(msg: Any) -> str:
    if isinstance(msg, dict):
        c = msg.get("content", "")
    else:
        c = getattr(msg, "content", "")
    if isinstance(c, list):
        return "\n".join(part.get("text", "") if isinstance(part, dict) else str(getattr(part, "text", "")) for part in c)
    return str(c or "")
