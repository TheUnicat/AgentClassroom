"""Provider-aware single-criterion judge call.

Each per-criterion LLM judge function in this package is a thin wrapper that
fills in `criterion_id`, `description`, and `anchors` and delegates to
`single_criterion_call` here. This module owns:

- Building the per-criterion prompt (same shape as the batched
  `TRANSCRIPT_JUDGE_PROMPT` in `teachingbench.prompts`, but scoped to ONE
  criterion).
- Provider dispatch via `teachingbench.client_utils.detect_provider`:
    * OpenAI: chat.completions.create with a strict json_schema response
      format. Schema is flat: `{value: number|null, rationale: string}`.
    * Anthropic: messages.create with forced tool use. Tool input schema is
      the same `{value, rationale}` shape. Ephemeral cache_control is set on
      both the system block and the tool definition so repeat per-criterion
      calls within 5 min only pay full price on the variable user message.
- Failure handling: any exception, parse error, or missing field returns
  `{"value": None, "rationale": "judge_error: ...", "raw": {}}` so a single
  bad call never crashes the composer.

Anthropic gotchas handled here:
- `temperature` is dropped before the call (deprecated for claude-opus-4-7).
- A small `<parameter name="...">` XML recovery path catches the ~17% of
  Opus tool calls that emit XML inside the JSON tool input. For a flat
  two-field schema like this it's rarely needed, but we handle it anyway.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from typing import Any

from teachingbench.client_utils import detect_provider

# Retry settings — see grader/judge.py for the same pattern.
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.5


def _should_retry(exc: BaseException) -> bool:
    code = getattr(exc, "status_code", None)
    if code is not None:
        return code == 429 or 500 <= code < 600
    name = type(exc).__name__.lower()
    return any(t in name for t in ("timeout", "connection", "apiconnect"))


async def _with_retry(label: str, coro_factory):
    last_exc: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return await coro_factory()
        except BaseException as e:  # noqa: BLE001
            last_exc = e
            if attempt == _MAX_RETRIES - 1 or not _should_retry(e):
                raise
            delay = _BACKOFF_BASE_S * (2 ** attempt) * (0.5 + random.random())
            logger.warning(
                "%s attempt %d/%d failed (%s); retrying in %.1fs",
                label, attempt + 1, _MAX_RETRIES, type(e).__name__, delay,
            )
            await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc

logger = logging.getLogger(__name__)


# JSON schema shared by both providers. Two fields, both required.
_FLAT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["value", "rationale"],
    "properties": {
        "value": {
            "type": ["number", "null"],
            "description": "Score in [0, 1], or null if the criterion does not apply.",
        },
        "rationale": {
            "type": "string",
            "description": "One- or two-sentence justification for the score.",
        },
    },
}


def _format_anchors(anchors: list[dict[str, Any]]) -> str:
    """Render anchors as a bullet list. Matches the batched judge's format."""
    if not anchors:
        return "(no anchors — score on the description alone)"
    lines: list[str] = []
    for a in anchors:
        score = a.get("score")
        label = "null" if score is None else f"{float(score):.2f}"
        lines.append(f"  - {label} → {a.get('meaning', '')}")
    return "\n".join(lines)


def _build_user_prompt(
    *,
    criterion_id: str,
    description: str,
    anchors: list[dict[str, Any]],
    materials: str,
    topic: str,
    transcript: str,
) -> str:
    """Build the user-facing prompt for one criterion."""
    return (
        "You are grading a tutoring session against a SINGLE criterion.\n\n"
        f"Topic: {topic}\n\n"
        f"Materials the student had:\n<materials>\n{materials}\n</materials>\n\n"
        f"Criterion: **{criterion_id}**\n"
        f"{description}\n\n"
        "Anchors (calibration points — interpolate freely):\n"
        f"{_format_anchors(anchors)}\n\n"
        f"Transcript:\n<transcript>\n{transcript}\n</transcript>\n\n"
        "Score this criterion in [0, 1] OR return null if it doesn't apply "
        "(see the description above for when null is appropriate). Return "
        "only a JSON object matching the schema."
    )


def _clamp01_or_none(v: Any) -> float | None:
    """Clamp a numeric value to [0, 1]; pass through None; coerce junk to None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return max(0.0, min(1.0, f))


# Recovery for the Opus XML-inside-JSON edge case:
# `<parameter name="value">0.7</parameter><parameter name="rationale">...</parameter>`
_XML_PARAM_RE = re.compile(
    r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>',
    re.DOTALL,
)


def _recover_xml_params(s: str) -> dict[str, Any] | None:
    """Best-effort recovery for Opus emitting XML <parameter> tags as tool input."""
    matches = _XML_PARAM_RE.findall(s)
    if not matches:
        return None
    out: dict[str, Any] = {}
    for name, raw in matches:
        raw = raw.strip()
        if name == "value":
            if raw.lower() in ("null", "none", ""):
                out[name] = None
            else:
                try:
                    out[name] = float(raw)
                except ValueError:
                    out[name] = None
        else:
            out[name] = raw
    return out or None


async def single_criterion_call(
    judge_client: Any,
    judge_model: str,
    *,
    criterion_id: str,
    description: str,
    anchors: list[dict[str, Any]],
    materials: str,
    topic: str,
    transcript: str,
    sampling_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run ONE LLM judge call for ONE criterion.

    Returns `{"value": float|None, "rationale": str, "raw": dict}`. Never
    raises — failures collapse to `{"value": None, "rationale": "judge_error:
    ...", "raw": {}}`.
    """
    provider = detect_provider(judge_model)
    prompt = _build_user_prompt(
        criterion_id=criterion_id,
        description=description,
        anchors=anchors,
        materials=materials,
        topic=topic,
        transcript=transcript,
    )
    if provider == "anthropic":
        parsed_or_err = await _anthropic_call(
            judge_client, judge_model, criterion_id, prompt, sampling_args
        )
    else:
        parsed_or_err = await _openai_call(
            judge_client, judge_model, criterion_id, prompt, sampling_args
        )

    if "error" in parsed_or_err:
        return {"value": None, "rationale": parsed_or_err["error"], "raw": {}}

    parsed = parsed_or_err["parsed"]
    if not isinstance(parsed, dict):
        return {"value": None, "rationale": "parse_error", "raw": {}}

    value = _clamp01_or_none(parsed.get("value"))
    rationale = str(parsed.get("rationale") or "")
    return {"value": value, "rationale": rationale, "raw": parsed}


async def _openai_call(
    judge_client: Any,
    judge_model: str,
    criterion_id: str,
    prompt: str,
    sampling_args: dict[str, Any] | None,
) -> dict[str, Any]:
    """OpenAI Chat Completions with strict JSON schema for a single criterion."""
    args = dict(sampling_args or {})
    if "max_tokens" in args:
        args["max_completion_tokens"] = args.pop("max_tokens")
    args = {k: v for k, v in args.items() if v is not None}

    async def _call():
        return await judge_client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": f"criterion_{criterion_id}",
                    "strict": True,
                    "schema": _FLAT_SCHEMA,
                },
            },
            **args,
        )
    try:
        resp = await _with_retry(f"OpenAI judge[{criterion_id}]", _call)
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("OpenAI single-criterion call failed after retries (%s): %s", criterion_id, e)
        return {"error": f"judge_error: {e}"}

    try:
        return {"parsed": json.loads(raw)}
    except json.JSONDecodeError:
        return {"error": "parse_error"}


async def _anthropic_call(
    judge_client: Any,
    judge_model: str,
    criterion_id: str,
    prompt: str,
    sampling_args: dict[str, Any] | None,
) -> dict[str, Any]:
    """Anthropic Messages with forced tool use for a single criterion.

    System block and tool definition are marked `cache_control: ephemeral` so
    they are cacheable across criteria/calls within the 5-min window. The
    variable user prompt is the only uncached portion.
    """
    system_text = (
        "You are grading a tutoring session against a single criterion. "
        "Return either a number in [0, 1] OR null (if the criterion does not "
        "apply to this transcript — see the criterion description for when "
        "null is appropriate). The anchors are calibration points, not the "
        "only allowed values — interpolate freely between them. Submit your "
        "score and a short rationale via the `report_criterion_score` tool."
    )
    tool_def = {
        "name": "report_criterion_score",
        "description": f"Submit the score and rationale for criterion '{criterion_id}'.",
        "input_schema": _FLAT_SCHEMA,
        "cache_control": {"type": "ephemeral"},
    }
    args = dict(sampling_args or {})
    args.pop("max_completion_tokens", None)
    args.pop("temperature", None)  # deprecated for claude-opus-4-7
    args.setdefault("max_tokens", 1024)
    args = {k: v for k, v in args.items() if v is not None}

    async def _call():
        return await judge_client.messages.create(
            model=judge_model,
            system=[
                {
                    "type": "text",
                    "text": system_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": "report_criterion_score"},
            **args,
        )
    try:
        resp = await _with_retry(f"Anthropic judge[{criterion_id}]", _call)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            cw = getattr(usage, "cache_creation_input_tokens", 0)
            cr = getattr(usage, "cache_read_input_tokens", 0)
            it = getattr(usage, "input_tokens", 0)
            logger.debug(
                "Opus cache (%s): writes=%s reads=%s non-cached_input=%s",
                criterion_id, cw, cr, it,
            )
    except Exception as e:
        logger.warning("Anthropic single-criterion call failed after retries (%s): %s", criterion_id, e)
        return {"error": f"judge_error: {e}"}

    for block in resp.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "report_criterion_score"
        ):
            tool_input = block.input
            if isinstance(tool_input, dict):
                # Opus sometimes emits XML <parameter> tags inside string fields.
                # If `value` looks like XML, try to recover.
                if isinstance(tool_input.get("rationale"), str) and "<parameter" in tool_input["rationale"]:
                    recovered = _recover_xml_params(tool_input["rationale"])
                    if recovered is not None:
                        return {"parsed": recovered}
                return {"parsed": tool_input}
            if isinstance(tool_input, str):
                # Try plain JSON first, then XML-parameter recovery.
                try:
                    return {"parsed": json.loads(tool_input)}
                except (json.JSONDecodeError, TypeError):
                    recovered = _recover_xml_params(tool_input)
                    if recovered is not None:
                        return {"parsed": recovered}
                    return {"error": "parse_error"}
            return {"error": "parse_error"}
    return {"error": "no tool_use block in response"}


# --- batched (multi-criterion) call ---------------------------------------
#
# `single_criterion_call` makes one LLM call per criterion — clean isolation,
# but costly when a composer wants 5+ criteria from the same transcript.
# `batched_criterion_call` packages N criteria into ONE call, returning N
# scores with their own rationales. Structurally similar to v1's batched
# judge in `grader.judge.judge_transcript`, but flat schema and per-criterion
# rationale instead of one overall rationale.
#
# Not wired into any composer yet — available for composers that opt in
# (e.g. v2_hybrid grouping all its LLM-side criteria into one call).


def _build_batched_schema(criteria: list[dict[str, Any]]) -> dict[str, Any]:
    """JSON schema with one nested {value, rationale} object per criterion id."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for c in criteria:
        cid = c["id"]
        properties[cid] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["value", "rationale"],
            "properties": {
                "value": {
                    "type": ["number", "null"],
                    "description": c.get("description", "")[:200] or
                                   f"Score for {cid} in [0,1] or null.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Short justification for the score.",
                },
            },
        }
        required.append(cid)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _build_batched_user_prompt(
    *,
    criteria: list[dict[str, Any]],
    materials: str,
    topic: str,
    transcript: str,
) -> str:
    lines = [
        "You are grading a tutoring session against MULTIPLE criteria.",
        "",
        f"Topic: {topic}",
        "",
        f"Materials the student had:\n<materials>\n{materials}\n</materials>",
        "",
        "Criteria (score each independently in [0, 1] or return null):",
    ]
    for i, c in enumerate(criteria, 1):
        cid = c["id"]
        desc = c.get("description", "")
        lines.append("")
        lines.append(f"  ({i}) **{cid}**")
        lines.append(f"      {desc}")
        anchors = c.get("anchors") or []
        if anchors:
            lines.append("      Anchors:")
            for a in anchors:
                score = a.get("score")
                label = "null" if score is None else f"{float(score):.2f}"
                lines.append(f"        - {label} → {a.get('meaning', '')}")
    lines += [
        "",
        f"Transcript:\n<transcript>\n{transcript}\n</transcript>",
        "",
        "Score each criterion independently — don't compensate across them "
        "(the composite is computed downstream). Anchors are calibration "
        "points; interpolate freely. Return ONLY a JSON object matching the "
        "schema: one nested {value, rationale} object per criterion id.",
    ]
    return "\n".join(lines)


def _normalize_batched_parsed(
    parsed: Any,
    criteria: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Coerce a parsed payload into `{crit_id: {value, rationale, raw}}` for
    every requested criterion. Missing criteria → value=None, rationale=
    'missing'. Malformed entries → value=None, rationale='parse_error'."""
    out: dict[str, dict[str, Any]] = {}
    for c in criteria:
        cid = c["id"]
        entry = parsed.get(cid) if isinstance(parsed, dict) else None
        if not isinstance(entry, dict):
            out[cid] = {"value": None, "rationale": "missing", "raw": {}}
            continue
        out[cid] = {
            "value": _clamp01_or_none(entry.get("value")),
            "rationale": str(entry.get("rationale") or ""),
            "raw": entry,
        }
    return out


async def batched_criterion_call(
    judge_client: Any,
    judge_model: str,
    *,
    criteria: list[dict[str, Any]],
    materials: str,
    topic: str,
    transcript: str,
    sampling_args: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Score multiple criteria in ONE LLM call.

    `criteria`: list of `{"id": str, "description": str, "anchors": [...]}`
    dicts — same shape used in `DEFAULT_RUBRIC` and the per-criterion
    function modules.

    Returns `{crit_id: {"value": float|None, "rationale": str, "raw": dict}}`
    for every criterion in the input, including ones the judge couldn't
    score (those come back as `value=None, rationale="missing"`). Never
    raises — failures collapse to all-None results with an error rationale.
    """
    if not criteria:
        return {}

    provider = detect_provider(judge_model)
    prompt = _build_batched_user_prompt(
        criteria=criteria, materials=materials, topic=topic, transcript=transcript,
    )
    schema = _build_batched_schema(criteria)
    schema_name = f"batched_criteria_{'_'.join(c['id'] for c in criteria)[:60]}"

    if provider == "anthropic":
        parsed_or_err = await _anthropic_batched(
            judge_client, judge_model, schema, schema_name, prompt, sampling_args,
        )
    else:
        parsed_or_err = await _openai_batched(
            judge_client, judge_model, schema, schema_name, prompt, sampling_args,
        )

    if "error" in parsed_or_err:
        msg = parsed_or_err["error"]
        return {c["id"]: {"value": None, "rationale": msg, "raw": {}} for c in criteria}

    return _normalize_batched_parsed(parsed_or_err["parsed"], criteria)


async def _openai_batched(
    judge_client: Any,
    judge_model: str,
    schema: dict[str, Any],
    schema_name: str,
    prompt: str,
    sampling_args: dict[str, Any] | None,
) -> dict[str, Any]:
    args = dict(sampling_args or {})
    if "max_tokens" in args:
        args["max_completion_tokens"] = args.pop("max_tokens")
    args = {k: v for k, v in args.items() if v is not None}
    try:
        resp = await judge_client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name[:64],
                    "strict": True,
                    "schema": schema,
                },
            },
            **args,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("OpenAI batched-criterion call failed: %s", e)
        return {"error": f"judge_error: {e}"}
    try:
        return {"parsed": json.loads(raw)}
    except json.JSONDecodeError:
        return {"error": "parse_error"}


async def _anthropic_batched(
    judge_client: Any,
    judge_model: str,
    schema: dict[str, Any],
    schema_name: str,
    prompt: str,
    sampling_args: dict[str, Any] | None,
) -> dict[str, Any]:
    system_text = (
        "You are grading a tutoring session against multiple criteria. "
        "Score each criterion independently in [0, 1] or null. Anchors "
        "are calibration points — interpolate freely. Submit your scores "
        "via the `report_batched_scores` tool."
    )
    tool_def = {
        "name": "report_batched_scores",
        "description": "Submit per-criterion score and rationale objects.",
        "input_schema": schema,
        "cache_control": {"type": "ephemeral"},
    }
    args = dict(sampling_args or {})
    args.pop("max_completion_tokens", None)
    args.pop("temperature", None)
    args.setdefault("max_tokens", 4096)
    args = {k: v for k, v in args.items() if v is not None}
    try:
        resp = await judge_client.messages.create(
            model=judge_model,
            system=[{"type": "text", "text": system_text,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": "report_batched_scores"},
            **args,
        )
    except Exception as e:
        logger.warning("Anthropic batched-criterion call failed: %s", e)
        return {"error": f"judge_error: {e}"}

    for block in resp.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", None) == "report_batched_scores"
        ):
            tool_input = block.input
            if isinstance(tool_input, dict):
                return {"parsed": tool_input}
            if isinstance(tool_input, str):
                try:
                    return {"parsed": json.loads(tool_input)}
                except (json.JSONDecodeError, TypeError):
                    recovered = _recover_xml_params(tool_input)
                    if recovered is not None:
                        return {"parsed": recovered}
                    return {"error": "parse_error"}
            return {"error": "parse_error"}
    return {"error": "no tool_use block in response"}


__all__ = ["single_criterion_call", "batched_criterion_call"]
