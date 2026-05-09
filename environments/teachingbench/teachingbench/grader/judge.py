"""TeachingRubric — subclass of `vf.JudgeRubric`. v0.1 reward = LLM judge scores the
full chat transcript against the per-task rubric (no quiz, no self-rating).

Reads `info["rubric"]`, `info["materials"]`, `info["topic"]` for the judge prompt.
Caches the parsed judge breakdown in `state["judge_breakdown"]` so sub-metric reward
funcs can read it without re-calling the judge.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import verifiers as vf
from openai import AsyncOpenAI

from teachingbench.prompts import DEFAULT_RUBRIC, TRANSCRIPT_JUDGE_PROMPT

logger = logging.getLogger(__name__)


class TeachingRubric(vf.JudgeRubric):
    def __init__(
        self,
        judge_client: AsyncOpenAI | None = None,
        judge_model: str = "gpt-5.4-nano",
        judge_sampling_args: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            judge_client=judge_client,
            judge_model=judge_model,
            judge_prompt=TRANSCRIPT_JUDGE_PROMPT,
            judge_sampling_args=judge_sampling_args or {"temperature": 0.2},
            **kwargs,
        )
        self.add_reward_func(_transcript_score, weight=1.0)
        self.add_metric(_judge_score_count)


async def _transcript_score(
    judge_client: AsyncOpenAI,
    judge_model: str,
    judge_sampling_args: dict[str, Any],
    prompt: Any,
    completion: Any,
    state: Any,
    info: Any,
    **_: Any,
) -> float:
    info_dict = _info_dict(info)
    rubric_text = info_dict.get("rubric") or DEFAULT_RUBRIC
    materials = info_dict.get("materials", "")
    topic = info_dict.get("topic", "")
    transcript = _render_transcript(prompt, completion)

    judge_prompt = TRANSCRIPT_JUDGE_PROMPT.format(
        topic=topic, materials=materials, rubric=rubric_text, transcript=transcript
    )

    args = dict(judge_sampling_args or {})
    if "max_tokens" in args:
        args["max_completion_tokens"] = args.pop("max_tokens")
    args = {k: v for k, v in args.items() if v is not None}

    try:
        resp = await judge_client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": judge_prompt}],
            **args,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("Transcript judge call failed: %s", e)
        _stash(state, {"scores": {}, "rationale": f"judge_error: {e}"})
        return 0.0

    parsed = _parse_json(raw, default={"scores": {}, "rationale": "parse_error"})
    scores = parsed.get("scores")
    if not isinstance(scores, dict) or not scores:
        # Fallback: maybe the judge returned a flat {"score": x}
        flat = parsed.get("score")
        if isinstance(flat, (int, float)):
            scores = {"overall": float(flat)}
            parsed["scores"] = scores

    if isinstance(scores, dict) and scores:
        nums = [_clamp01(v) for v in scores.values() if isinstance(v, (int, float))]
        composite = sum(nums) / len(nums) if nums else 0.0
    else:
        composite = 0.0

    _stash(state, {"scores": scores or {}, "rationale": parsed.get("rationale", ""), "composite": composite})
    return composite


async def _judge_score_count(state: Any, **_: Any) -> float:
    breakdown = _stash_get(state)
    scores = breakdown.get("scores") if isinstance(breakdown, dict) else None
    return float(len(scores) if isinstance(scores, dict) else 0)


_transcript_score.__name__ = "transcript_score"
_judge_score_count.__name__ = "num_rubric_criteria"


# --- helpers ---


def _render_transcript(prompt: Any, completion: Any) -> str:
    """Build a Tutor:/Student: transcript from prompt + completion, dropping system msgs."""
    msgs: list[Any] = []
    if isinstance(prompt, list):
        msgs.extend(prompt)
    if isinstance(completion, list):
        msgs.extend(completion)
    lines: list[str] = []
    for m in msgs:
        role = _role(m)
        if role == "system":
            continue
        if role == "tool":
            content = _content(m)
            lines.append(f"[Tool result]: {content}")
            continue
        speaker = "Tutor" if role == "assistant" else "Student"
        content = _content(m)
        if content:
            lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


def _info_dict(info: Any) -> dict[str, Any]:
    if isinstance(info, dict):
        return info
    if isinstance(info, str):
        try:
            return json.loads(info)
        except json.JSONDecodeError:
            return {}
    return {}


def _stash(state: Any, breakdown: dict[str, Any]) -> None:
    if isinstance(state, dict):
        state["judge_breakdown"] = breakdown
    else:
        try:
            state["judge_breakdown"] = breakdown
        except Exception:
            setattr(state, "judge_breakdown", breakdown)


def _stash_get(state: Any) -> dict[str, Any]:
    if isinstance(state, dict):
        v = state.get("judge_breakdown")
    else:
        v = getattr(state, "judge_breakdown", None)
    return v if isinstance(v, dict) else {}


def _clamp01(v: Any) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, f))


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
        logger.warning("Could not parse JSON from judge response: %r", raw[:200])
        return default


def _role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    return str(getattr(msg, "role", ""))


def _content(msg: Any) -> Any:
    if isinstance(msg, dict):
        c = msg.get("content", "")
    else:
        c = getattr(msg, "content", "")
    if isinstance(c, list):
        return "\n".join(part.get("text", "") if isinstance(part, dict) else str(getattr(part, "text", "")) for part in c)
    return str(c or "")
