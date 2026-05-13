"""det_with_atq: all deterministic functions + answers_the_question (LLM).

A coherence-check composer. The deterministic stack carries the bulk of
the signal (volume, sycophancy, structure, dialogue, vocabulary,
readability, code validity), with `answers_the_question` as the only
LLM-judged criterion — used as a bullshit filter ("did the teacher
actually answer what was asked, or perform good-teaching gestures around
empty content?").

This is NOT the final v2_hybrid composer. It's the smallest hybrid we
can build to validate that the deterministic functions agree with
human/LLM judgment about teaching quality in the broad. If composites
here track v1_llm_only reasonably on normal rollouts but diverge on
reward-hacky ones (where det catches things ATQ misses), the
deterministic stack is coherent enough to build on.

Per-criterion ceiling: only `answers_the_question` has one configured
(cap_at_zero=0.20 in reward_scoring.py). So if the LLM judges that the
teacher didn't actually answer the question, the composite is hard-
capped at 0.20 regardless of how clean the deterministic side looks.
"""

from __future__ import annotations

from typing import Any

from teachingbench.grader.composers.base import default_compose
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
    sycophancy_regex,
    turn_asymmetry,
    type_token_ratio,
)
from teachingbench.grader.functions.llm import answers_the_question

NAME = "det_with_atq"

# Weights sum to 1.0. ATQ is the heaviest individual term — it's the only
# LLM signal and the bullshit-filter. The deterministic side groups
# roughly to:
#   ~33% firehose / volume signals (anti_firehose_length + first_msg +
#        listicle_density + turn_asymmetry) — the dominant AI-tutor
#        failure mode, weighted accordingly
#   ~18% dialogue / scaffolding (echo + question_density + concept_velocity)
#   ~14% topic-stay / content (seed_question_recall + code_validity)
#   ~11% style / clarity (flesch_kincaid + type_token_ratio)
#   ~7%  sycophancy
WEIGHTS: dict[str, float] = {
    "answers_the_question":  0.18,
    "anti_firehose_length":  0.10,
    "first_message_length":  0.10,
    "listicle_density":      0.08,
    "turn_asymmetry":        0.05,
    "sycophancy_regex":      0.07,
    "echo_score":            0.06,
    "seed_question_recall":  0.07,
    "question_density":      0.05,
    "concept_velocity":      0.05,
    "flesch_kincaid":        0.06,
    "type_token_ratio":      0.05,
    "code_validity":         0.08,   # None on non-CS tasks → renormalized away
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, f"weights sum {sum(WEIGHTS.values())} != 1.0"

_DET_FNS: dict[str, Any] = {
    "anti_firehose_length":  anti_firehose_length.score,
    "first_message_length":  first_message_length.score,
    "listicle_density":      listicle_density.score,
    "turn_asymmetry":        turn_asymmetry.score,
    "sycophancy_regex":      sycophancy_regex.score,
    "echo_score":            echo_score.score,
    "seed_question_recall":  seed_question_recall.score,
    "question_density":      question_density.score,
    "concept_velocity":      concept_velocity.score,
    "flesch_kincaid":        flesch_kincaid.score,
    "type_token_ratio":      type_token_ratio.score,
    "code_validity":         code_validity.score,
}


async def score(
    messages: list[dict],
    task_info: dict,
    *,
    judge_client: Any = None,
    judge_model: str | None = None,
    judge_sampling_args: dict[str, Any] | None = None,
) -> dict:
    if judge_client is None or judge_model is None:
        raise ValueError(
            "det_with_atq requires judge_client + judge_model for "
            "answers_the_question (the only LLM term in this composer)."
        )

    # 1. Deterministic functions: pure, synchronous.
    scores: dict[str, float | None] = {
        cid: fn(messages, task_info) for cid, fn in _DET_FNS.items()
    }

    # 2. LLM: answers_the_question only.
    atq = await answers_the_question.score(
        messages, task_info,
        judge_client=judge_client,
        judge_model=judge_model,
        sampling_args=judge_sampling_args,
    )
    scores["answers_the_question"] = atq.get("value")

    # 3. Compose. reward_scoring.compute_composite handles None scores by
    # renormalizing weights over the rest, so code_validity returning None
    # on math tasks just redistributes its share.
    return default_compose(
        scores,
        WEIGHTS,
        rationale=str(atq.get("rationale") or "").strip(),
        rubric=[],
        extra_terms={"atq_raw": atq.get("raw", {})},
    )
