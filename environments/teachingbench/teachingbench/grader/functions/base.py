"""Protocols for judge functions.

A judge "function" is a single scoring concern (factual correctness,
sycophancy detection, message length, etc.). Functions come in two flavors:

- Deterministic: pure Python, no I/O, no LLM. Cheap, noiseless. Measures
  mechanical/structural features. Lives under `functions/deterministic/`.
- LLM-backed: async, takes a judge client. Slower and costly. Measures
  semantic content. Lives under `functions/llm/`.

Both score a transcript on [0, 1] and may return None to signal "doesn't
apply to this rollout" (e.g. `bridging` when no materials were shared, or
`code_validity` on a non-code task). Composers handle None by
renormalizing weights over the remaining criteria.

Modularity discipline:
- `functions/deterministic/` must not import `verifiers`, `openai`,
  `anthropic`, or any teachingbench-specific module. Only stdlib + small
  helper utilities. This keeps the subtree liftable into a standalone
  judging repo unchanged.
- `functions/llm/` may import provider SDK clients, but takes prompts and
  task data as args — no teachingbench-specific imports beyond shared
  helper utilities.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


class LLMResult(TypedDict, total=False):
    value: float | None
    rationale: str
    raw: dict[str, Any]


@runtime_checkable
class Deterministic(Protocol):
    """A pure deterministic scoring function.

    Implementations expose a module-level `score(messages, task_info)`
    callable matching this signature.

    Args:
        messages: full transcript including system messages. Implementations
            should filter for whatever they care about (e.g. teacher turns).
        task_info: the per-rollout `info` dict (rubric, materials, topic,
            subject, difficulty, turns, ...).

    Returns:
        A float in [0, 1] or None. Must be deterministic — same inputs always
        produce the same output.
    """

    def __call__(self, messages: list[dict], task_info: dict) -> float | None: ...


class LLM(Protocol):
    """An LLM-backed scoring function.

    Implementations expose a module-level `async score(messages, task_info,
    *, judge_client, judge_model, sampling_args=None)` matching this
    signature.

    Returns an LLMResult dict:
        value:     float in [0, 1] or None (N/A)
        rationale: short natural-language explanation from the judge
        raw:       parsed provider payload (for debugging / replay)
    """

    async def __call__(
        self,
        messages: list[dict],
        task_info: dict,
        *,
        judge_client: Any,
        judge_model: str,
        sampling_args: dict[str, Any] | None = None,
    ) -> LLMResult: ...


__all__ = ["Deterministic", "LLM", "LLMResult"]
