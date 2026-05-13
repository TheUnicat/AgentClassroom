"""state_v1: trajectory composer (per-turn state values + outcome roll-up).

Same criteria + weights as `v2_hybrid`, but the per-turn-natural functions
are evaluated AFTER EACH TEACHER TURN (state-based), producing a
trajectory of per-turn signal vectors stored in `composite_terms.trajectory`.
The aggregate composite is then computed by averaging non-None per-turn
values for those criteria, plus the existing sequence-level / outcome
signals for the rest.

What changes vs v2_hybrid:
- Per-turn deterministic functions are called on conversation PREFIXES
  (`messages[:msg_idx+1]` for each teacher turn). They expose a `score_turn`
  module-level function that returns the state value at that point.
- The aggregate for those criteria is `mean(non-None per-turn values)`,
  which is conceptually a state-averaged signal rather than a
  rollout-level aggregate. For most criteria the two agree closely; where
  they differ (e.g. anti_firehose_length, listicle_density), the per-turn
  mean is the better failure-mode signal (one bad turn isn't averaged
  away by surrounding good ones).
- Sequence-level deterministic functions (`concept_velocity`,
  `type_token_ratio`, `seed_question_recall`) stay outcome-level — they
  measure cross-turn variance / diversity / drift, not per-turn state.
- LLM functions stay outcome-level for now (one call per rollout).
  Per-turn LLM scoring is a follow-up — it'd 4× the call count and
  needs separate calibration.

The trajectory output is the dense state-value sequence that's useful
for (a) debugging single rollouts (see where teaching broke down) and
(b) future RL training where per-step rewards beat outcome-only.

Same WEIGHTS as v2_hybrid so composites are directly comparable.
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

NAME = "state_v1"

# Mirror v2_hybrid exactly so the difference is *only* the per-turn vs
# rollout-aggregate scoring path.
WEIGHTS: dict[str, float] = {
    "answers_the_question":    0.18,
    "anti_firehose":           0.14,
    "no_excessive_validation": 0.08,
    "anti_firehose_length":    0.08,
    "first_message_length":    0.08,
    "listicle_density":        0.06,
    "turn_asymmetry":          0.04,
    "seed_question_recall":    0.07,
    "code_validity":           0.04,
    "echo_score":              0.05,
    "concept_velocity":        0.04,
    "question_density":        0.05,
    "flesch_kincaid":          0.05,
    "type_token_ratio":        0.04,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, f"weights sum {sum(WEIGHTS.values())} != 1.0"


# Per-turn-natural: called on each `messages[:teacher_msg_idx+1]` slice
_PER_TURN_DET: dict[str, Any] = {
    "anti_firehose_length":  anti_firehose_length,
    "first_message_length":  first_message_length,
    "listicle_density":      listicle_density,
    "turn_asymmetry":        turn_asymmetry,
    "echo_score":            echo_score,
    "question_density":      question_density,
    "flesch_kincaid":        flesch_kincaid,
    "code_validity":         code_validity,
}

# Sequence-level deterministic: stay outcome-level
_SEQ_DET: dict[str, Any] = {
    "concept_velocity":     concept_velocity,
    "type_token_ratio":     type_token_ratio,
    "seed_question_recall": seed_question_recall,
}

# LLM: outcome-level for state_v1 (per-turn LLM is a separate composer)
_LLM_FNS: dict[str, Any] = {
    "answers_the_question":    answers_the_question,
    "anti_firehose":           anti_firehose,
    "no_excessive_validation": no_excessive_validation,
}


def _role(m: Any) -> str:
    if isinstance(m, dict):
        return str(m.get("role", ""))
    return str(getattr(m, "role", ""))


def _teacher_msg_indices(messages: list[dict]) -> list[int]:
    return [i for i, m in enumerate(messages) if _role(m) == "assistant"]


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
            "state_v1 requires judge_client + judge_model for the three "
            "outcome-level LLM criteria."
        )

    # 1) Build the per-turn trajectory.
    t_msg_idxs = _teacher_msg_indices(messages)
    trajectory: list[dict[str, Any]] = []
    for tk, msg_idx in enumerate(t_msg_idxs):
        slice_ = messages[: msg_idx + 1]
        turn_scores: dict[str, float | None] = {}
        for cid, mod in _PER_TURN_DET.items():
            turn_scores[cid] = mod.score_turn(slice_, task_info)
        trajectory.append({"turn": tk + 1, "msg_idx": msg_idx, "scores": turn_scores})

    # 2) Aggregate per-turn signals: mean of non-None values per criterion.
    aggregated: dict[str, float | None] = {}
    for cid in _PER_TURN_DET:
        vals = [t["scores"][cid] for t in trajectory if t["scores"][cid] is not None]
        aggregated[cid] = sum(vals) / len(vals) if vals else None

    # 3) Sequence-level deterministic: run on full messages.
    for cid, mod in _SEQ_DET.items():
        aggregated[cid] = mod.score(messages, task_info)

    # 4) LLM (outcome-level), routed through cached_judge.
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
        aggregated[cid] = result.get("value")
        rat = (result.get("rationale") or "").strip()
        if rat:
            rationales.append(f"[{cid}] {rat}")

    return default_compose(
        aggregated,
        WEIGHTS,
        rationale="\n".join(rationales),
        rubric=[],
        extra_terms={"trajectory": trajectory},
    )
