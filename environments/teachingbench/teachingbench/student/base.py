"""Student protocol. Active method in v0.1 is `respond`. The others are deprecated
shapes from the quiz/self-rating reward design — kept around for re-enablement later."""

from __future__ import annotations

from typing import Any, Literal, Protocol, TypedDict, runtime_checkable


class AskDecision(TypedDict):  # legacy (quiz path)
    action: Literal["follow_up", "ready"]
    question: str | None


class SelfRating(TypedDict, total=False):  # legacy (self-rating path)
    clarity: int
    coverage: int
    confidence: int
    still_confusing: str


@runtime_checkable
class Student(Protocol):
    """Student-side actor in the multi-turn dialog."""

    async def respond(
        self,
        messages: list[dict[str, Any]],
        *,
        topic: str,
        materials: str,
        system_prompt: str,
    ) -> str:
        """Produce the next student-side message given the conversation so far."""
        ...

    # --- Legacy methods (not used by env_response in v0.1; kept for later re-enable). ---

    async def decide(self, messages: list[dict[str, Any]], *, topic: str, materials: str) -> AskDecision:
        ...

    async def answer_quiz(
        self, quiz: list[dict[str, Any]], *, topic: str, teaching_trace: list[dict[str, Any]]
    ) -> list[Any]:
        ...

    async def self_rate(self, *, topic: str) -> SelfRating:
        ...
