"""Human-in-the-loop student. Stub kept for future use; LLMStudent is the v0.1 focus."""

from __future__ import annotations

from typing import Any

from teachingbench.student.base import AskDecision, SelfRating


class HumanStudent:
    """Stub. Will read from stdin / a UI adapter when prioritized post-v0.1."""

    async def decide(self, messages: list[dict[str, Any]], *, topic: str, materials: str) -> AskDecision:
        raise NotImplementedError("HumanStudent is deferred. Use LLMStudent for v0.1.")

    async def answer_quiz(
        self,
        quiz: list[dict[str, Any]],
        *,
        topic: str,
        teaching_trace: list[dict[str, Any]],
    ) -> list[Any]:
        raise NotImplementedError

    async def self_rate(self, *, topic: str) -> SelfRating:
        raise NotImplementedError
