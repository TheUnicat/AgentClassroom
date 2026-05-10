"""TeachingRubric — subclass of `vf.JudgeRubric`. Reward = LLM judge scores the full
chat transcript against a fixed-schema rubric.

The rubric is a list of {id, description, anchors} criteria (see `prompts.DEFAULT_RUBRIC`
for the default and `dataset._validate_rubric` for the schema). Each task can ship its own.

The judge call uses OpenAI structured outputs (`response_format={"type": "json_schema",
"strict": true, ...}`) where the schema is built dynamically from the criterion ids:
required fields, type number, additionalProperties false. The judge cannot return missing
fields, extra fields, wrong types, or non-numbers. We then clamp to [0, 1] and average.

Per-criterion scores + rationale land in `state["judge_breakdown"]` for inspection
(pass `state_columns=["judge_breakdown"]` to `env.evaluate` to surface them in outputs).
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


async def judge_transcript(
    judge_client: AsyncOpenAI,
    judge_model: str,
    *,
    rubric: list[dict[str, Any]],
    materials: str,
    topic: str,
    transcript: str,
    sampling_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the LLM judge ONCE on a rendered transcript.

    Returns `{scores, rationale, composite, rubric, error?}`. `scores` is a dict
    keyed by criterion id — values are floats in [0, 1] or `None` (for criteria
    the judge marked N/A). `composite` is the mean of non-null scores.

    Used by both the env's `_transcript_score` reward function and the
    judge-reliability test in `teachingbench.reliability_check`. Pure function:
    no state mutation.
    """
    judge_prompt = TRANSCRIPT_JUDGE_PROMPT.format(
        topic=topic,
        materials=materials,
        rubric_text=_format_rubric(rubric),
        transcript=transcript,
    )
    schema = _build_response_schema(rubric)

    args = dict(sampling_args or {})
    if "max_tokens" in args:
        args["max_completion_tokens"] = args.pop("max_tokens")
    args = {k: v for k, v in args.items() if v is not None}

    try:
        resp = await judge_client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": judge_prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "teaching_rubric_score", "strict": True, "schema": schema},
            },
            **args,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("Transcript judge call failed: %s", e)
        return {"scores": {}, "rationale": f"judge_error: {e}", "composite": 0.0, "rubric": rubric, "error": str(e)}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("Judge returned non-JSON despite strict mode: %s — raw=%r", e, raw[:200])
        return {"scores": {}, "rationale": "parse_error", "composite": 0.0, "rubric": rubric, "error": "parse_error"}

    raw_scores = parsed.get("scores") or {}
    scores: dict[str, float | None] = {}
    for c in rubric:
        v = raw_scores.get(c["id"])
        scores[c["id"]] = None if v is None else _clamp01(v)
    nums = [v for v in scores.values() if isinstance(v, (int, float))]
    composite = sum(nums) / len(nums) if nums else 0.0
    rationale = str(parsed.get("rationale") or "")

    return {"scores": scores, "rationale": rationale, "composite": composite, "rubric": rubric}


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
    rubric = info_dict.get("rubric")
    if not isinstance(rubric, list) or not rubric:
        rubric = DEFAULT_RUBRIC

    breakdown = await judge_transcript(
        judge_client,
        judge_model,
        rubric=rubric,
        materials=info_dict.get("materials", ""),
        topic=info_dict.get("topic", ""),
        transcript=_render_transcript(prompt, completion),
        sampling_args=judge_sampling_args,
    )
    _stash(state, breakdown)
    return float(breakdown.get("composite", 0.0))


async def _judge_score_count(state: Any, **_: Any) -> float:
    breakdown = _stash_get(state)
    scores = breakdown.get("scores") if isinstance(breakdown, dict) else None
    return float(len(scores) if isinstance(scores, dict) else 0)


_transcript_score.__name__ = "transcript_score"
_judge_score_count.__name__ = "num_rubric_criteria"


# --- helpers ---


def _build_response_schema(rubric: list[dict]) -> dict[str, Any]:
    """Build a strict JSON Schema from the rubric criterion ids.

    Each criterion is `["number", "null"]` — null signals "this criterion doesn't apply
    to this transcript" (e.g. bridging when no materials were shared). Null scores are
    skipped when computing the composite, not counted as zero.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for c in rubric:
        cid = c["id"]
        properties[cid] = {
            "type": ["number", "null"],
            "description": c.get("description", "") or f"Score for criterion {cid}.",
        }
        required.append(cid)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["scores", "rationale"],
        "properties": {
            "scores": {
                "type": "object",
                "additionalProperties": False,
                "required": required,
                "properties": properties,
            },
            "rationale": {"type": "string"},
        },
    }


def _format_rubric(rubric: list[dict]) -> str:
    """Render the rubric as a numbered list with anchors inline, for the judge prompt."""
    lines: list[str] = []
    for i, c in enumerate(rubric, 1):
        lines.append(f"{i}. **{c['id']}** — {c['description']}")
        for a in c.get("anchors") or []:
            score = a.get("score")
            label = "null" if score is None else f"{float(score):.2f}"
            lines.append(f"     - {label} → {a['meaning']}")
    return "\n".join(lines)


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
