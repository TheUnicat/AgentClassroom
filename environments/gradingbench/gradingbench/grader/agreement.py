"""GradingRubric — `vf.Rubric` subclass scoring grader-vs-human agreement.

Single primary reward function `_grade_agreement`:
    reward = 1 - abs(pred - actual) / 3
    (exact match = 1.0, off by 1 = 0.67, off by 2 = 0.33, off by 3 = 0.0)

Secondary metric `_exact_match` (0 or 1) for diagnostic plotting.

Parsing: the grader is asked to emit `{"grade": <int>, "rationale": "<str>"}`. We parse
the model's final assistant message tolerantly:
1. Try `json.loads(content)` directly.
2. Try extracting a JSON object substring.
3. Provider-aware: if the model emitted Anthropic tool_use blocks, pull the input.
4. Fallback: regex for ``"grade":\\s*([1-4])``.

If all parses fail, log a warning and return 0.0 (worst-case agreement).

Provider-aware structured-output dispatch (`_call_grader_openai_structured`,
`_call_grader_anthropic_structured`) is provided for callers that want to *force* JSON
output before calling the env's rollout path. The env itself does not invoke these —
verifiers drives the rollout and passes us the completion. The dispatch is sibling-
shaped with `teachingbench/grader/judge.py::_judge_openai_call` /
`_judge_anthropic_call` for consistency.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import verifiers as vf

logger = logging.getLogger(__name__)

# Fixed 1-4 ordinal scale. Max possible distance is 3.
_GRADE_MIN = 1
_GRADE_MAX = 4
_GRADE_SPAN = float(_GRADE_MAX - _GRADE_MIN)  # 3.0

_GRADE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["grade", "rationale"],
    "properties": {
        "grade": {"type": "integer", "minimum": _GRADE_MIN, "maximum": _GRADE_MAX},
        "rationale": {"type": "string"},
    },
}


class GradingRubric(vf.Rubric):
    def __init__(
        self,
        judge_client: Any | None = None,
        judge_model: str = "gpt-5.4-nano",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        # Kept for sibling-API parity with teachingbench; the agreement reward is
        # deterministic, but a future judge-LLM-based variant would use these.
        self._judge_client = judge_client
        self._judge_model = judge_model
        self.add_reward_func(_grade_agreement, weight=1.0)
        self.add_metric(_exact_match)


# --- reward + metric functions ---


async def _grade_agreement(
    completion: Any,
    state: Any,
    info: Any,
    **_: Any,
) -> float:
    """Primary reward: 1 - |pred - actual| / 3."""
    actual = _ground_truth_grade(info)
    if actual is None:
        logger.warning("grade_agreement: no ground_truth_grade in info; returning 0.0")
        _stash(state, {"pred": None, "actual": None, "rationale": "",
                        "agreement": 0.0, "exact": 0, "parse_error": "no_ground_truth"})
        return 0.0

    parsed = _parse_grader_output(completion)
    pred = parsed.get("grade")
    rationale = str(parsed.get("rationale") or "")
    parse_error = parsed.get("error")

    if pred is None:
        logger.warning("grade_agreement: failed to parse grader output (%s); returning 0.0", parse_error)
        _stash(state, {"pred": None, "actual": actual, "rationale": rationale,
                        "agreement": 0.0, "exact": 0, "parse_error": parse_error or "no_grade"})
        return 0.0

    pred_clamped = max(_GRADE_MIN, min(_GRADE_MAX, int(pred)))
    diff = abs(pred_clamped - actual)
    agreement = 1.0 - (diff / _GRADE_SPAN)
    exact = 1 if pred_clamped == actual else 0
    _stash(state, {
        "pred": pred_clamped,
        "actual": actual,
        "rationale": rationale,
        "agreement": agreement,
        "exact": exact,
        "parse_error": None,
    })
    return float(agreement)


async def _exact_match(state: Any, **_: Any) -> float:
    """Secondary metric: 1.0 if pred == actual, else 0.0. Reads what `_grade_agreement` stashed."""
    breakdown = _stash_get(state)
    return float(breakdown.get("exact", 0))


_grade_agreement.__name__ = "grade_agreement"
_exact_match.__name__ = "exact_match"


# --- output parsing ---


def _parse_grader_output(completion: Any) -> dict[str, Any]:
    """Tolerant parse of the grader's final message into `{"grade": int|None, "rationale": str, "error": str|None}`.

    Tries structured paths first (Anthropic tool_use input, OpenAI JSON content),
    then falls back to a regex grab. Never raises.
    """
    text, tool_input = _extract_text_and_tool_input(completion)

    # 1) Anthropic tool_use input (already a dict)
    if isinstance(tool_input, dict) and "grade" in tool_input:
        grade = _coerce_grade(tool_input.get("grade"))
        return {"grade": grade, "rationale": str(tool_input.get("rationale") or ""),
                "error": None if grade is not None else "bad_grade_in_tool_input"}

    if not text:
        return {"grade": None, "rationale": "", "error": "empty_completion"}

    # 2) Plain json.loads
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "grade" in obj:
            grade = _coerce_grade(obj.get("grade"))
            return {"grade": grade, "rationale": str(obj.get("rationale") or ""),
                    "error": None if grade is not None else "bad_grade_field"}
    except json.JSONDecodeError:
        pass

    # 3) Substring extract: first {...} block
    obj_substr = _extract_json_object(text)
    if obj_substr is not None:
        try:
            obj = json.loads(obj_substr)
            if isinstance(obj, dict) and "grade" in obj:
                grade = _coerce_grade(obj.get("grade"))
                return {"grade": grade, "rationale": str(obj.get("rationale") or ""),
                        "error": None if grade is not None else "bad_grade_field"}
        except json.JSONDecodeError:
            pass

    # 4) Last-resort regex
    m = re.search(r'"grade"\s*:\s*([1-4])', text)
    if m:
        return {"grade": int(m.group(1)), "rationale": "", "error": "regex_fallback"}
    m = re.search(r"\b(?:grade|score)\s*[:=]?\s*([1-4])\b", text, re.IGNORECASE)
    if m:
        return {"grade": int(m.group(1)), "rationale": "", "error": "regex_fallback"}

    return {"grade": None, "rationale": "", "error": "parse_failed"}


def _extract_text_and_tool_input(completion: Any) -> tuple[str, Any]:
    """Pull text content + (optionally) an Anthropic-style tool_use input dict out of `completion`."""
    if completion is None:
        return "", None

    # Verifiers typically passes completion as a list of message dicts.
    if isinstance(completion, list):
        text_parts: list[str] = []
        tool_input: Any = None
        for m in completion:
            role = _role(m)
            if role and role != "assistant":
                continue
            content = _content(m)
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                    if btype == "text":
                        text_parts.append(
                            block.get("text", "") if isinstance(block, dict)
                            else getattr(block, "text", "")
                        )
                    elif btype == "tool_use":
                        tool_input = (
                            block.get("input") if isinstance(block, dict)
                            else getattr(block, "input", None)
                        )
            # OpenAI-style tool_calls on the message itself
            tcs = m.get("tool_calls") if isinstance(m, dict) else getattr(m, "tool_calls", None)
            if tcs:
                for tc in tcs:
                    fn = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)
                    args = fn.get("arguments") if isinstance(fn, dict) else getattr(fn, "arguments", None)
                    if isinstance(args, str):
                        try:
                            tool_input = json.loads(args)
                        except json.JSONDecodeError:
                            pass
                    elif isinstance(args, dict):
                        tool_input = args
        return "\n".join(t for t in text_parts if t), tool_input

    if isinstance(completion, str):
        return completion, None

    # Single message dict
    if isinstance(completion, dict):
        content = completion.get("content", "")
        return (str(content) if isinstance(content, str) else ""), None

    return str(completion), None


def _extract_json_object(text: str) -> str | None:
    """Find the first balanced `{...}` substring. Returns None if not found."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _coerce_grade(v: Any) -> int | None:
    """Coerce to an int in [1, 4]; return None if it can't be."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    g = int(round(f))
    if g < _GRADE_MIN or g > _GRADE_MAX:
        return None
    return g


# --- provider-aware structured-output dispatch (sibling-shaped helpers) ---


async def _call_grader_openai_structured(
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
    sampling_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Force OpenAI to emit `{grade, rationale}` via a strict JSON schema.

    Returns `{"parsed": {...}}` on success, `{"error": "..."}` on failure.
    Mirrors `teachingbench/grader/judge.py::_judge_openai_call`.
    """
    args = dict(sampling_args or {})
    if "max_tokens" in args:
        args["max_completion_tokens"] = args.pop("max_tokens")
    args = {k: v for k, v in args.items() if v is not None}
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "grading_rubric_score",
                    "strict": True,
                    "schema": _GRADE_JSON_SCHEMA,
                },
            },
            **args,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("OpenAI grader call failed: %s", e)
        return {"error": f"grader_error: {e}"}
    try:
        return {"parsed": json.loads(raw)}
    except json.JSONDecodeError:
        return {"error": "parse_error"}


async def _call_grader_anthropic_structured(
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
    sampling_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Force Anthropic to emit `{grade, rationale}` via tool use.

    Returns `{"parsed": {...}}` on success, `{"error": "..."}` on failure.
    Mirrors `teachingbench/grader/judge.py::_judge_anthropic_call` but flat schema —
    no per-criterion fan-out, just `{grade, rationale}`.
    """
    tool_def = {
        "name": "report_grade",
        "description": "Submit the integer grade and a short rationale.",
        "input_schema": _GRADE_JSON_SCHEMA,
    }
    args = dict(sampling_args or {})
    args.pop("max_completion_tokens", None)
    args.pop("temperature", None)  # Opus 4.7 deprecates this
    args.setdefault("max_tokens", 1024)
    args = {k: v for k, v in args.items() if v is not None}
    try:
        resp = await client.messages.create(
            model=model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": "report_grade"},
            **args,
        )
    except Exception as e:
        logger.warning("Anthropic grader call failed: %s", e)
        return {"error": f"grader_error: {e}"}
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_grade":
            tool_input = block.input
            if isinstance(tool_input, dict):
                return {"parsed": tool_input}
            try:
                return {"parsed": json.loads(tool_input)}
            except (json.JSONDecodeError, TypeError):
                return {"error": "parse_error"}
    return {"error": "no tool_use block in response"}


# --- state stashing + small utils ---


def _stash(state: Any, breakdown: dict[str, Any]) -> None:
    if isinstance(state, dict):
        state["grading_breakdown"] = breakdown
    else:
        try:
            state["grading_breakdown"] = breakdown
        except Exception:
            setattr(state, "grading_breakdown", breakdown)


def _stash_get(state: Any) -> dict[str, Any]:
    if isinstance(state, dict):
        v = state.get("grading_breakdown")
    else:
        v = getattr(state, "grading_breakdown", None)
    return v if isinstance(v, dict) else {}


def _ground_truth_grade(info: Any) -> int | None:
    d = _info_dict(info)
    v = d.get("ground_truth_grade")
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _info_dict(info: Any) -> dict[str, Any]:
    if isinstance(info, dict):
        return info
    if isinstance(info, str):
        try:
            return json.loads(info)
        except json.JSONDecodeError:
            return {}
    return {}


def _role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    return str(getattr(msg, "role", ""))


def _content(msg: Any) -> Any:
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "")
