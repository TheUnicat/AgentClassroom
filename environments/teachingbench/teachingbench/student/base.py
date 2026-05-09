"""Student protocol. LLM and human implementations both satisfy it."""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict, runtime_checkable


class AskDecision(TypedDict):
    action: Literal["follow_up", "ready"]
    question: str | None


class SelfRating(TypedDict, total=False):
    clarity: int
    coverage: int
    confidence: int
    still_confusing: str


@runtime_checkable
class Student(Protocol):
    """Anything that can decide follow-ups, take a quiz, and self-rate."""

    async def decide(self, messages: list[dict[str, Any]], *, topic: str, materials: str) -> AskDecision:
        """After the tutor's latest turn, ask another question or signal ready."""
        ...

    async def answer_quiz(
        self,
        quiz: list[dict[str, Any]],
        *,
        topic: str,
        teaching_trace: list[dict[str, Any]],
    ) -> list[Any]:
        """Answer each quiz item. Returns one answer per item, in order."""
        ...

    async def self_rate(self, *, topic: str) -> SelfRating:
        """Self-rate clarity / coverage / confidence + a free-text 'still confusing' note."""
        ...
