"""v2_hybrid: 3 LLM criteria + 11 deterministic functions.

LLM side (3 criteria, all routed through `cached_judge` so v1's batched
scores are reused without re-judging):

  - **answers_the_question** — gating bullshit filter ("did the teacher
    actually answer the question, or perform good-teaching gestures
    around hollow content?"). Heaviest single weight; per-criterion
    ceiling at 0.20 in reward_scoring.PER_CRITERION_CEILING_AT_ZERO,
    so a zero here hard-caps the composite.
  - **anti_firehose** — the LLM's holistic read on whether the teacher
    information-dumped. Layered on top of the deterministic length and
    structure signals — det catches the mechanical pattern (long first
    message, listicle density), LLM catches the *kind* of long (e.g.
    a long-but-necessary code walkthrough should not be penalized).
  - **no_excessive_validation** — LLM's read on sycophancy. The
    deterministic `sycophancy_regex` is essentially dead on SOTA models
    (no stock-opener hits), so it's excluded from this composer — the
    LLM does all the sycophancy work here.

Deterministic side: 11 of the 12 functions (sycophancy_regex removed —
redundant with the LLM term, no signal on SOTA models). The two
anti_firehose-adjacent signals (length, structure) ARE kept alongside
the LLM anti_firehose term — they capture mechanical patterns LLMs
grade unreliably.

Weights (sum = 1.0):
  LLM: 0.18 + 0.14 + 0.08 = 0.40
  Det: 0.60  (firehose/length 0.26, content 0.20, dialogue/style 0.14)

Reward-hack detector is NOT wired in here yet (PLAN_v2.md has it as a
hard cap in the full v2_hybrid; we'll add when calibration warrants).
"""

from __future__ import annotations

import asyncio
from typing import Any

from teachingbench.grader.composers.base import default_compose
from teachingbench.grader.judge_cache import cached_judge
from teachingbench.grader.functions.deterministic import (
    anti_firehose_length,
    code_validity,
    concept_velocity,
    echo_score,
    first_message_length,
    flesch_kincaid,
    listicle_density,
    question_density,
    seed_question_recall,
    turn_asymmetry,
    type_token_ratio,
)
from teachingbench.grader.functions.llm import (
    answers_the_question,
    anti_firehose,
    no_excessive_validation,
)

NAME = "v2_hybrid"

WEIGHTS: dict[str, float] = {
    # LLM side
    "answers_the_question":    0.18,
    "anti_firehose":           0.14,
    "no_excessive_validation": 0.08,    # bumped from 0.06 (absorbed dropped sycophancy_regex weight)
    # Deterministic — firehose / length
    "anti_firehose_length":    0.08,
    "first_message_length":    0.08,
    "listicle_density":        0.06,
    "turn_asymmetry":          0.04,
    # Deterministic — content / topic stay
    "seed_question_recall":    0.07,
    "code_validity":           0.04,    # None for non-CS → renormalized away
    "echo_score":              0.05,
    "concept_velocity":        0.04,
    # Deterministic — dialogue / style
    "question_density":        0.05,
    "flesch_kincaid":          0.05,
    "type_token_ratio":        0.04,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, f"weights sum {sum(WEIGHTS.values())} != 1.0"


_DET_FNS: dict[str, Any] = {
    "anti_firehose_length":  anti_firehose_length.score,
    "first_message_length":  first_message_length.score,
    "listicle_density":      listicle_density.score,
    "turn_asymmetry":        turn_asymmetry.score,
    "seed_question_recall":  seed_question_recall.score,
    "code_validity":         code_validity.score,
    "echo_score":            echo_score.score,
    "concept_velocity":      concept_velocity.score,
    "question_density":      question_density.score,
    "flesch_kincaid":        flesch_kincaid.score,
    "type_token_ratio":      type_token_ratio.score,
}

_LLM_FNS: dict[str, Any] = {
    "answers_the_question":    answers_the_question,
    "anti_firehose":           anti_firehose,
    "no_excessive_validation": no_excessive_validation,
}


async def score(
    messages: list[dict],
    task_info: dict,
    *,
    judge_client: Any = None,
    judge_model: str | None = None,
    judge_sampling_args: dict[str, Any] | None = None,
    cache: dict | None = None,
    force_recall: bool = False,
) -> dict:
    if judge_client is None or judge_model is None:
        raise ValueError(
            "v2_hybrid requires judge_client + judge_model for its three "
            "LLM criteria (answers_the_question, anti_firehose, "
            "no_excessive_validation)."
        )

    # Deterministic: pure, synchronous, fast.
    scores: dict[str, float | None] = {
        cid: fn(messages, task_info) for cid, fn in _DET_FNS.items()
    }

    # LLM: fan out the 3 criteria concurrently. Each goes through
    # cached_judge so v1's batched judge_breakdown.scores is reused
    # without re-judging (legacy fallback path).
    llm_results = await asyncio.gather(*[
        cached_judge(
            cache,
            criterion_id=cid,
            llm_fn=fn,
            messages=messages,
            task_info=task_info,
            judge_client=judge_client,
            judge_model=judge_model,
            sampling_args=judge_sampling_args,
            force_recall=force_recall,
            composer_name=NAME,
        )
        for cid, fn in _LLM_FNS.items()
    ])
    rationales: list[str] = []
    for (cid, _), result in zip(_LLM_FNS.items(), llm_results):
        scores[cid] = result.get("value")
        rat = (result.get("rationale") or "").strip()
        if rat:
            rationales.append(f"[{cid}] {rat}")

    return default_compose(
        scores,
        WEIGHTS,
        rationale="\n".join(rationales),
        rubric=[],
    )
