"""TeachingEnv — multi-turn tutor / student / quiz / self-rate / score pipeline.

Subclasses `vf.MultiTurnEnv`. The model under test is the tutor. The env-side actor
is the student (LLM in v0.1; HumanStudent stub kept for later). When the student
signals "ready" or `max_student_turns` is reached, env_response synchronously runs
the quiz, self-rating, and scoring, stashes them in state, and terminates the rollout
via `state["final_env_response"]`. Reward funcs (in `TeachingRubric`) read those
fields after the rollout completes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import verifiers as vf
from openai import AsyncOpenAI
from verifiers.types import ToolCall, ToolMessage
from verifiers.utils.tool_utils import convert_func_to_tool_def, is_valid_tool_content_parts

from teachingbench.dataset import build_dataset
from teachingbench.grader.judge import TeachingRubric
from teachingbench.grader.quiz import generate_quiz, score_quiz
from teachingbench.prompts import TUTOR_SYSTEM_PROMPT
from teachingbench.student.base import Student
from teachingbench.student.llm import LLMStudent
from teachingbench.tools import TOOLS

logger = logging.getLogger(__name__)


def load_environment(
    *,
    judge_client: AsyncOpenAI | None = None,
    judge_model: str = "gpt-4.1-nano",
    student_client: AsyncOpenAI | None = None,
    student_model: str | None = None,
    max_student_turns: int = 8,
    max_turns: int = 24,
    pass_threshold: float = 0.6,
    task_filter: str | None = None,
    **kwargs: Any,
) -> vf.Environment:
    """Verifiers entry point. Don't pin the tutor model here — Verifiers passes it into rollout."""
    rubric = TeachingRubric(judge_client=judge_client, judge_model=judge_model)
    dataset = build_dataset(task_filter=task_filter)
    return TeachingEnv(
        dataset=dataset,
        rubric=rubric,
        student_client=student_client,
        student_model=student_model,
        max_student_turns=max_student_turns,
        max_turns=max_turns,
        pass_threshold=pass_threshold,
        tools=TOOLS,
        **kwargs,
    )


class TeachingEnv(vf.MultiTurnEnv):
    def __init__(
        self,
        *,
        student_client: AsyncOpenAI | None = None,
        student_model: str | None = None,
        max_student_turns: int = 8,
        tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._tools = list(tools or [])
        self._tool_map = {
            getattr(t, "__name__", t.__class__.__name__): t for t in self._tools
        }
        tool_defs = [convert_func_to_tool_def(t) for t in self._tools] if self._tools else None

        super().__init__(tool_defs=tool_defs, **kwargs)

        self._student_client = student_client
        self._student_model = student_model
        self._max_student_turns = max_student_turns

    async def setup_state(self, state: vf.State) -> vf.State:
        info = _info_dict(state)
        materials = info.get("materials", "")
        topic = info.get("topic", "(unknown topic)")
        subject = info.get("subject", "(unknown subject)")

        # Inject the system prompt (with materials interpolated) at the front of the prompt.
        system_prompt = TUTOR_SYSTEM_PROMPT.format(materials=materials, topic=topic)
        state["prompt"] = _ensure_system(state["prompt"], system_prompt)

        state["materials"] = materials
        state["topic"] = topic
        state["subject"] = subject
        state["max_student_turns"] = self._max_student_turns
        state["student_turns"] = 0
        state["teaching_phase"] = "teaching"
        return state

    async def env_response(self, messages: vf.Messages, state: vf.State, **_: Any) -> vf.Messages:
        assert isinstance(messages, list) and messages, "env_response called with empty messages"
        last = messages[-1]

        # 1) Tutor called tools — dispatch and feed results back. Don't increment turn count.
        tool_calls = _tool_calls(last)
        if tool_calls:
            return await self._dispatch_tools(tool_calls)

        # 2) Tutor produced a text turn. Decide: continue dialog or finalize?
        state["student_turns"] = int(state.get("student_turns", 0)) + 1
        student = self._make_student(state)

        if state["student_turns"] >= state["max_student_turns"]:
            return await self._finalize(messages, state, student, reason="turn_cap")

        try:
            decision = await student.decide(
                _as_dicts(messages),
                topic=state["topic"],
                materials=state["materials"],
            )
        except Exception as e:
            logger.warning("student.decide failed (%s); finalizing.", e)
            return await self._finalize(messages, state, student, reason="student_error")

        if decision.get("action") == "ready":
            return await self._finalize(messages, state, student, reason="student_ready")

        question = decision.get("question") or "Could you say more?"
        return [{"role": "user", "content": question}]

    async def _finalize(
        self,
        messages: vf.Messages,
        state: vf.State,
        student: Student,
        *,
        reason: str,
    ) -> vf.Messages:
        rubric = self.rubric  # TeachingRubric, owns judge_client + judge_model
        judge_client = getattr(rubric, "judge_client", None)
        judge_model = getattr(rubric, "judge_model", "gpt-4.1-nano")
        if judge_client is None:
            raise RuntimeError("TeachingEnv rubric is missing a judge_client.")

        teaching_trace = _as_dicts(messages)

        try:
            quiz = await generate_quiz(
                judge_client,
                judge_model,
                topic=state["topic"],
                materials=state["materials"],
                teaching_trace=teaching_trace,
            )
        except Exception as e:
            logger.warning("generate_quiz failed: %s", e)
            quiz = []

        try:
            answers = await student.answer_quiz(
                quiz, topic=state["topic"], teaching_trace=teaching_trace
            )
        except Exception as e:
            logger.warning("student.answer_quiz failed: %s", e)
            answers = []

        try:
            self_rating = await student.self_rate(topic=state["topic"])
        except Exception as e:
            logger.warning("student.self_rate failed: %s", e)
            self_rating = {"clarity": 3, "coverage": 3, "confidence": 3, "still_confusing": ""}

        breakdown = await score_quiz(
            judge_client,
            judge_model,
            quiz=quiz,
            answers=answers,
            self_rating=self_rating,
        )

        state["quiz"] = quiz
        state["quiz_answers"] = answers
        state["self_rating"] = self_rating
        state["reward_breakdown"] = breakdown
        state["teaching_phase"] = "done"
        state["finalize_reason"] = reason

        summary = (
            f"[Session ended: {reason}. "
            f"Quiz: {breakdown['quiz_score']:.2f} ({len(quiz)} items), "
            f"self-rating: {breakdown['self_rating_score']:.2f}, "
            f"composite: {breakdown['composite']:.2f}.]"
        )
        final_msg: list[dict[str, Any]] = [{"role": "user", "content": summary}]
        state["final_env_response"] = final_msg
        return final_msg

    async def _dispatch_tools(self, tool_calls: list[Any]) -> vf.Messages:
        results: list[Any] = []
        for tc in tool_calls:
            name = _tc_field(tc, "name")
            args_raw = _tc_field(tc, "arguments") or "{}"
            tc_id = _tc_field(tc, "id") or ""
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except json.JSONDecodeError as e:
                results.append(
                    ToolMessage(role="tool", content=f"tool args parse error: {e}", tool_call_id=tc_id)
                )
                continue
            tool = self._tool_map.get(name)
            if tool is None:
                results.append(
                    ToolMessage(role="tool", content=f"unknown tool: {name}", tool_call_id=tc_id)
                )
                continue
            try:
                result = await tool(**args)
            except Exception as e:
                results.append(
                    ToolMessage(role="tool", content=f"tool error: {e}", tool_call_id=tc_id)
                )
                continue
            content = result if is_valid_tool_content_parts(result) else json.dumps(result)
            results.append(ToolMessage(role="tool", content=content, tool_call_id=tc_id))
        return results

    def _make_student(self, state: vf.State) -> Student:
        rubric = self.rubric
        client = self._student_client or getattr(rubric, "judge_client", None)
        model = self._student_model or getattr(rubric, "judge_model", "gpt-4.1-nano")
        if client is None:
            raise RuntimeError("TeachingEnv has no student_client and rubric has no judge_client.")
        return LLMStudent(client=client, model=model)


def _info_dict(state: vf.State) -> dict[str, Any]:
    info = state.get("info") if isinstance(state, dict) else None
    if isinstance(info, str):
        try:
            return json.loads(info)
        except json.JSONDecodeError:
            return {}
    if isinstance(info, dict):
        return info
    return {}


def _ensure_system(prompt: Any, system_content: str) -> Any:
    """Prepend or replace the system message with our task-specialized one."""
    if isinstance(prompt, list) and prompt and _role(prompt[0]) == "system":
        return [{"role": "system", "content": system_content}] + list(prompt[1:])
    if isinstance(prompt, list):
        return [{"role": "system", "content": system_content}] + list(prompt)
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": str(prompt)},
    ]


def _tool_calls(msg: Any) -> list[Any]:
    if isinstance(msg, dict):
        tc = msg.get("tool_calls") or []
    else:
        tc = getattr(msg, "tool_calls", None) or []
    return list(tc) if tc else []


def _tc_field(tc: Any, name: str) -> Any:
    if isinstance(tc, dict):
        return tc.get(name) if name in ("id",) else (tc.get("function", {}) or {}).get(name, tc.get(name))
    if isinstance(tc, ToolCall):
        return getattr(tc, name, None)
    return getattr(tc, name, None)


def _as_dicts(messages: vf.Messages) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if isinstance(m, dict):
            out.append(m)
        else:
            out.append({"role": _role(m), "content": _content(m)})
    return out


def _role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    return str(getattr(msg, "role", ""))


def _content(msg: Any) -> Any:
    if isinstance(msg, dict):
        return msg.get("content", "")
    return getattr(msg, "content", "")
