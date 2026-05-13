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

import asyncio
import json
import logging
import os
import random
from typing import Any

import verifiers as vf
from openai import AsyncOpenAI

# Retry settings for transient API errors (429 rate-limit, 5xx server errors,
# timeouts, transient network glitches). Does NOT retry on 4xx auth/billing
# errors — those are persistent and re-issuing the same call won't help.
_MAX_RETRIES = 3
_BACKOFF_BASE_S = 1.5  # 1.5s, 3s, 6s with jitter


def _should_retry(exc: BaseException) -> bool:
    """Decide whether an exception is worth retrying. Transient errors only —
    429s, 5xxs, timeouts, connection resets. Persistent errors (401 auth,
    402 billing, 400 bad request) are NOT retried."""
    # OpenAI/Anthropic SDKs expose `status_code` on their HTTP error subclasses.
    code = getattr(exc, "status_code", None)
    if code is not None:
        if code == 429:  # rate limit
            return True
        if 500 <= code < 600:  # server errors
            return True
        return False  # 401, 402, 403, 404, 400 — don't retry
    # Heuristic: timeouts, connection issues
    name = type(exc).__name__.lower()
    if any(t in name for t in ("timeout", "connection", "apiconnect")):
        return True
    return False


async def _with_retry(label: str, coro_factory):
    """Call `coro_factory()` (a no-arg callable returning a fresh coroutine)
    up to _MAX_RETRIES times, with jittered exponential backoff between
    attempts. Returns the awaited result or re-raises the final exception.
    """
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
        raise last_exc  # unreachable but pleases type-checker

from teachingbench.grader.reward_scoring import compute_composite, describe as describe_formula
from teachingbench.prompts import DEFAULT_RUBRIC, TRANSCRIPT_JUDGE_PROMPT

logger = logging.getLogger(__name__)


class TeachingRubric(vf.JudgeRubric):
    def __init__(
        self,
        judge_client: AsyncOpenAI | None = None,
        judge_model: str = "gpt-5.4",
        judge_sampling_args: dict[str, Any] | None = None,
        skip_judge: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            judge_client=judge_client,
            judge_model=judge_model,
            judge_prompt=TRANSCRIPT_JUDGE_PROMPT,
            judge_sampling_args=judge_sampling_args or {"temperature": 0.2},
            **kwargs,
        )
        # If skip_judge is True, we still register the reward func but it short-circuits
        # to 0.0 without calling the LLM. Use this for batch-rollout mode where you want
        # to save transcripts now and judge later (e.g. via the OpenAI Batch API).
        self._skip_judge = skip_judge
        if skip_judge:
            os.environ["TEACHINGBENCH_SKIP_JUDGE"] = "1"
        self.add_reward_func(_transcript_score, weight=1.0)
        self.add_metric(_judge_score_count)


async def judge_transcript(
    judge_client: Any,  # AsyncOpenAI or AsyncAnthropic
    judge_model: str,
    *,
    rubric: list[dict[str, Any]],
    materials: str,
    topic: str,
    transcript: str,
    sampling_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the LLM judge ONCE on a rendered transcript. Provider-aware: dispatches
    to OpenAI or Anthropic based on the model name. The caller must pass the
    matching client type.

    Returns `{scores, weights, composite, composite_raw, composite_terms,
    rationale, rubric, formula, error?}`.
    """
    from teachingbench.client_utils import detect_provider
    provider = detect_provider(judge_model)
    if provider == "anthropic":
        parsed_or_err = await _judge_anthropic_call(judge_client, judge_model, rubric, materials, topic, transcript, sampling_args)
    else:
        parsed_or_err = await _judge_openai_call(judge_client, judge_model, rubric, materials, topic, transcript, sampling_args)

    if "error" in parsed_or_err:
        return {"scores": {}, "weights": {}, "rationale": parsed_or_err["error"], "composite": 0.0,
                "rubric": rubric, "error": parsed_or_err["error"]}

    parsed = parsed_or_err["parsed"]
    raw_scores = parsed.get("scores") or {}
    # Defensive: some providers may emit `scores` as a JSON string inside the tool input.
    if isinstance(raw_scores, str):
        try:
            raw_scores = json.loads(raw_scores)
        except json.JSONDecodeError:
            raw_scores = {}
    if not isinstance(raw_scores, dict):
        raw_scores = {}
    scores: dict[str, float | None] = {}
    weights: dict[str, float] = {}
    for c in rubric:
        cid = c["id"]
        v = raw_scores.get(cid)
        scores[cid] = None if v is None else _clamp01(v)
        w = c.get("weight")
        weights[cid] = float(w) if isinstance(w, (int, float)) else 1.0 / len(rubric)

    composite_result = compute_composite(scores, weights)
    rationale = str(parsed.get("rationale") or "")

    return {
        "scores": scores,
        "weights": weights,
        "rationale": rationale,
        "composite": composite_result["composite"],
        "composite_raw": composite_result["composite_raw"],
        "composite_terms": composite_result["terms"],
        "formula": describe_formula(),
        "rubric": rubric,
    }


async def _judge_openai_call(
    judge_client: Any, judge_model: str, rubric: list[dict],
    materials: str, topic: str, transcript: str, sampling_args: dict | None,
) -> dict[str, Any]:
    """OpenAI Chat Completions with strict JSON schema."""
    judge_prompt = TRANSCRIPT_JUDGE_PROMPT.format(
        topic=topic, materials=materials,
        rubric_text=_format_rubric(rubric), transcript=transcript,
    )
    schema = _build_response_schema(rubric)
    args = dict(sampling_args or {})
    if "max_tokens" in args:
        args["max_completion_tokens"] = args.pop("max_tokens")
    args = {k: v for k, v in args.items() if v is not None}

    async def _call():
        return await judge_client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": judge_prompt}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "teaching_rubric_score", "strict": True, "schema": schema}},
            **args,
        )
    try:
        resp = await _with_retry("OpenAI judge", _call)
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        logger.warning("OpenAI judge call failed (after retries): %s", e)
        return {"error": f"judge_error: {e}"}

    try:
        return {"parsed": json.loads(raw)}
    except json.JSONDecodeError:
        return {"error": "parse_error"}


async def _judge_anthropic_call(
    judge_client: Any, judge_model: str, rubric: list[dict],
    materials: str, topic: str, transcript: str, sampling_args: dict | None,
) -> dict[str, Any]:
    """Anthropic Messages with structured output via forced tool use.

    Uses prompt caching on the rubric (system message) and tool definition so
    repeat judge calls within a 5-min window pay ~10% on the cached portion
    instead of full price. Saves ~$2 per 228 calls under our setup.
    """
    schema = _build_response_schema(rubric)
    # System message carries the static instructions + rubric (cacheable across calls).
    system_text = (
        "You are grading a tutoring session against a fixed rubric.\n\n"
        "Rubric (score each criterion in [0, 1]):\n"
        f"{_format_rubric(rubric)}\n\n"
        "Score each criterion independently on its own merits; the composite is computed "
        "downstream as a weighted combination, so do not try to weight or compensate across "
        "criteria yourself. The anchors are calibration points, not the only allowed values — "
        "interpolate freely between them. For each criterion, return either a number in [0, 1] "
        "OR null (if the criterion doesn't apply to this transcript — see each criterion's "
        "description for when null is appropriate). Submit your scores via the "
        "`report_rubric_scores` tool."
    )
    # User message carries the variable parts (different per call).
    user_text = (
        f"Topic: {topic}\n\n"
        f"Materials the student had:\n<materials>\n{materials}\n</materials>\n\n"
        f"Transcript:\n<transcript>\n{transcript}\n</transcript>"
    )
    # Tool definition (cacheable across calls).
    tool_def = {
        "name": "report_rubric_scores",
        "description": "Submit per-criterion rubric scores and an overall rationale.",
        "input_schema": schema,
        "cache_control": {"type": "ephemeral"},
    }
    args = dict(sampling_args or {})
    args.pop("max_completion_tokens", None)
    args.pop("temperature", None)  # Opus 4.7 deprecates this
    args.setdefault("max_tokens", 4096)
    args = {k: v for k, v in args.items() if v is not None}

    async def _call():
        return await judge_client.messages.create(
            model=judge_model,
            system=[{"type": "text", "text": system_text,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_text}],
            tools=[tool_def],
            tool_choice={"type": "tool", "name": "report_rubric_scores"},
            **args,
        )
    try:
        resp = await _with_retry("Anthropic judge", _call)
        # Log cache stats once per call so we can verify caching is working.
        usage = getattr(resp, "usage", None)
        if usage is not None:
            cw = getattr(usage, "cache_creation_input_tokens", 0)
            cr = getattr(usage, "cache_read_input_tokens", 0)
            it = getattr(usage, "input_tokens", 0)
            logger.info("Opus cache: writes=%s reads=%s non-cached_input=%s", cw, cr, it)
    except Exception as e:
        logger.warning("Anthropic judge call failed (after retries): %s", e)
        return {"error": f"judge_error: {e}"}

    # Find the tool_use block in the response
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == "report_rubric_scores":
            tool_input = block.input
            if isinstance(tool_input, dict):
                return {"parsed": tool_input}
            try:
                return {"parsed": json.loads(tool_input)}
            except (json.JSONDecodeError, TypeError):
                return {"error": "parse_error"}
    return {"error": "no tool_use block in response"}


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
    # Skip-judge mode for batch rollouts: just save the transcript with no score.
    # The rollout is still complete; we'll judge it later via judge_reliability_check
    # (n=1) or a batch-API judging script.
    if os.environ.get("TEACHINGBENCH_SKIP_JUDGE") == "1":
        _stash(state, {"scores": {}, "weights": {}, "composite": 0.0,
                       "rationale": "skipped", "rubric": [],
                       "skipped": True})
        return 0.0

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
