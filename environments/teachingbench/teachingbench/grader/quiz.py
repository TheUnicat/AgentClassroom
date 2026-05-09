"""Quiz generator + scorer. Quiz is generated post-teaching, conditioned on the trace."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from teachingbench.prompts import FREE_RESPONSE_JUDGE_PROMPT, QUIZ_GENERATOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


async def generate_quiz(
    client: AsyncOpenAI,
    model: str,
    *,
    topic: str,
    materials: str,
    teaching_trace: list[dict[str, Any]],
    sampling_args: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Produce 3 MCQ + 1 free-response items targeted at what the tutor actually taught."""
    args = sampling_args or {"temperature": 0.4}
    trace_text = _trace_to_text(teaching_trace)
    system_prompt = QUIZ_GENERATOR_SYSTEM_PROMPT.format(
        topic=topic, materials=materials, trace=trace_text
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Produce the quiz now."},
        ],
        **args,
    )
    raw = resp.choices[0].message.content or ""
    parsed = _parse_json(raw, default={"items": []})
    items = parsed.get("items", []) if isinstance(parsed, dict) else []
    return [item for item in items if _valid_quiz_item(item)]


async def score_quiz(
    client: AsyncOpenAI,
    model: str,
    *,
    quiz: list[dict[str, Any]],
    answers: list[Any],
    self_rating: dict[str, Any],
    sampling_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute per-item correctness, combine with self-rating into a reward dict."""
    args = sampling_args or {"temperature": 0.0}
    if not quiz:
        return _empty_breakdown(self_rating)

    per_item: list[dict[str, Any]] = []
    for item, ans in zip(quiz, _pad(answers, len(quiz))):
        if item["type"] == "mcq":
            correct = _mcq_correct(item, ans)
            per_item.append({"id": item.get("id"), "type": "mcq", "answer": ans, "correct": correct})
        else:
            correct = await _judge_free_response(client, model, item, ans, args)
            per_item.append({"id": item.get("id"), "type": "free", "answer": ans, "correct": correct})

    n = len(per_item)
    quiz_score = sum(1.0 for it in per_item if it["correct"]) / n if n else 0.0
    self_rating_score = _self_rating_to_score(self_rating)
    composite = (quiz_score + self_rating_score) / 2.0  # equal-weight to start (PLAN.md open item)
    return {
        "quiz_score": quiz_score,
        "self_rating_score": self_rating_score,
        "composite": composite,
        "per_item": per_item,
    }


async def _judge_free_response(
    client: AsyncOpenAI, model: str, item: dict[str, Any], answer: Any, sampling_args: dict[str, Any]
) -> bool:
    prompt = FREE_RESPONSE_JUDGE_PROMPT.format(
        question=item.get("question", ""),
        rubric=item.get("rubric", ""),
        answer=str(answer or ""),
    )
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            **sampling_args,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("Free-response judge call failed: %s", e)
        return False
    parsed = _parse_json(raw, default={"correct": False})
    return bool(parsed.get("correct"))


def _mcq_correct(item: dict[str, Any], answer: Any) -> bool:
    expected = str(item.get("answer", "")).strip().upper()
    given = str(answer or "").strip().upper()
    return bool(expected) and given == expected


def _self_rating_to_score(self_rating: dict[str, Any]) -> float:
    """Average the three Likert axes, normalize to [0, 1]. Free text is ignored for scoring."""
    axes = ["clarity", "coverage", "confidence"]
    vals = [self_rating.get(a) for a in axes]
    nums = [v for v in vals if isinstance(v, (int, float))]
    if not nums:
        return 0.0
    avg = sum(nums) / len(nums)  # 1..5
    return max(0.0, min(1.0, (avg - 1.0) / 4.0))


def _empty_breakdown(self_rating: dict[str, Any]) -> dict[str, Any]:
    self_rating_score = _self_rating_to_score(self_rating)
    return {
        "quiz_score": 0.0,
        "self_rating_score": self_rating_score,
        "composite": self_rating_score / 2.0,
        "per_item": [],
    }


def _valid_quiz_item(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if item.get("type") not in ("mcq", "free"):
        return False
    if not item.get("question"):
        return False
    if item["type"] == "mcq":
        opts = item.get("options")
        if not isinstance(opts, list) or len(opts) < 2:
            return False
        if not item.get("answer"):
            return False
    return True


def _pad(seq: list[Any], n: int) -> list[Any]:
    return list(seq) + [None] * max(0, n - len(seq))


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
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
        logger.warning("Could not parse JSON from grader response: %r", raw[:200])
        return default


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
