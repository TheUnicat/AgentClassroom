"""state_v1: trajectory composer (per-turn state values + delta evaluation).

Same criteria + weights as `v2_hybrid`, but built from per-turn state
values instead of one rollout-level aggregate per criterion. The
trajectory of per-turn signals is stored in `composite_terms.trajectory`
and ALSO mirrored into the row's `judge_cache` (model="deterministic",
turn=k) so other composers / inspections can read it without going
through state_v1.

Three classes of criteria, with three scoring paths:

  A. **Per-turn-natural** (9 fns: anti_firehose_length, first_message_length,
     listicle_density, turn_asymmetry, sycophancy_regex, echo_score,
     question_density, flesch_kincaid, code_validity, seed_question_recall).
     Each fn exposes `score_turn(messages_so_far, task_info)` which returns
     the *immediate reward* for the latest teacher turn — the score of THIS
     specific message, no contamination from earlier turns. This is the
     chess analog of `r_t = V_t - V_{t-1}` for stateless actions.

  B. **Sequence-level cumulative** (2 fns: concept_velocity, type_token_ratio).
     These measure CROSS-TURN structure (variance of novelty across turns,
     vocabulary diversity across all prose) — they have no meaningful "this
     turn alone" reading. We use **delta evaluation**:
         V(s_t) = score(messages[:msg_idx+1], task_info)
         r_t   = V(s_t) - V(s_{t-1})   with V(s_-1) := 0
     The first turn where V becomes defined gets r_t = V_t (treating the
     prior None as 0). Once both V_t and V_{t-1} are defined, r_t is a
     proper delta. This matches the chess-engine V(s)/r decomposition.

  C. **Outcome-level LLM** (3 fns: answers_the_question, anti_firehose,
     no_excessive_validation). One LLM call per rollout, cached. Per-turn
     LLM is a future-extension — disabled here to keep cost flat.

Aggregation for the final composite:
  - Per-turn-natural: mean of non-None per-turn values (same as before).
  - Sequence-level: V(s_final) — same number `score()` would return on
    the full rollout. The deltas are diagnostic, the aggregate is the
    final state value (chess-like).
  - LLM: outcome value, unchanged.

WEIGHTS mirror v2_hybrid exactly so composites are directly comparable.
"""

from __future__ import annotations

import asyncio
from typing import Any

from teachingbench.grader.composers.base import default_compose
from teachingbench.grader.judge_cache import cached_judge, store
from teachingbench.grader.reward_scoring import compute_composite
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
DETERMINISTIC_MODEL_TAG = "deterministic"

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


# Class A: per-turn-natural — each module exposes score_turn returning
# the immediate reward for the latest teacher turn given its history.
_PER_TURN_DET: dict[str, Any] = {
    "anti_firehose_length":  anti_firehose_length,
    "first_message_length":  first_message_length,
    "listicle_density":      listicle_density,
    "turn_asymmetry":        turn_asymmetry,
    "echo_score":            echo_score,
    "question_density":      question_density,
    "flesch_kincaid":        flesch_kincaid,
    "code_validity":         code_validity,
    "seed_question_recall":  seed_question_recall,
}

# Class B: sequence-level cumulative — score on prefix gives V(s_t),
# composer derives r_t = V_t - V_{t-1} for the trajectory.
_SEQ_DET: dict[str, Any] = {
    "concept_velocity":  concept_velocity,
    "type_token_ratio":  type_token_ratio,
}

# Class C: outcome-level LLM — one call per rollout, cached.
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


V0_BASELINE = 0.5  # neutral mid-scale baseline for the first turn's delta


def _delta_first_defined(prev: float | None, curr: float | None) -> float | None:
    """Per-criterion delta with the V(s_-1) := V0_BASELINE convention.

    - Both None → None (criterion stays undefined here)
    - curr None  → None
    - prev None, curr defined → curr - V0_BASELINE (signed first-defined reward;
      treats prior state as the mid-scale baseline so per-criterion deltas
      at T1 are good/bad signed, not always-positive)
    - both defined → curr - prev
    """
    if curr is None:
        return None
    if prev is None:
        return curr - V0_BASELINE
    return curr - prev


def _annotate_state_and_turn_scores(trajectory: list[dict]) -> None:
    """Mutate `trajectory` in place: add `state_value`, `turn_score`,
    `state_breakdown`, and `turn_breakdown` to each entry.

    State value at turn t = deterministic-only composite computed on the
    running aggregates of every det criterion up to t. We exclude the LLM
    criteria here because they're outcome-level (no per-turn value
    available). Weights are renormalized over det criteria only.

    Per-criterion running aggregates ("state_breakdown" at turn t):
      - class A (per-turn-natural): running mean of per-turn rewards up to t
      - class B (sequence-level):  V(s_t) at this turn

    Turn score at turn t = state_value(t) - state_value(t-1), with the
    first-turn baseline V(s_-1) := V0_BASELINE (default 0.5 — neutral
    mid-scale, not 0). The 0-baseline convention made every first turn
    register as +0.5 just for "the conversation existed"; a neutral
    baseline makes turn_score(0) signed and informative (positive if
    the opener was above-average, negative if below).

    Per-criterion turn deltas ("turn_breakdown" at turn t):
      - both defined → curr - prev
      - prev None, curr defined → curr - 0.5 (first-defined-turn signed delta)
      - curr None → None
    """
    det_crits = list(_PER_TURN_DET) + list(_SEQ_DET)
    weight_total = sum(WEIGHTS[c] for c in det_crits)
    det_weights = {c: WEIGHTS[c] / weight_total for c in det_crits}

    running_sums = {c: 0.0 for c in _PER_TURN_DET}
    running_n = {c: 0 for c in _PER_TURN_DET}
    prev_state_breakdown: dict[str, float | None] = {c: None for c in det_crits}
    prev_state_value: float | None = None

    for entry in trajectory:
        for cid in _PER_TURN_DET:
            v = entry["scores"].get(cid)
            if isinstance(v, (int, float)):
                running_sums[cid] += v
                running_n[cid] += 1

        state_breakdown: dict[str, float | None] = {}
        for cid in _PER_TURN_DET:
            n = running_n[cid]
            state_breakdown[cid] = running_sums[cid] / n if n > 0 else None
        for cid in _SEQ_DET:
            state_breakdown[cid] = entry["state"].get(cid)

        # det-only composite
        result = compute_composite(state_breakdown, det_weights)
        state_value = float(result["composite"])

        turn_breakdown: dict[str, float | None] = {}
        for cid in det_crits:
            curr = state_breakdown[cid]
            prev = prev_state_breakdown[cid]
            turn_breakdown[cid] = _delta_first_defined(prev, curr)

        prev_sv = prev_state_value if prev_state_value is not None else V0_BASELINE
        turn_score = state_value - prev_sv

        entry["state_value"] = state_value
        entry["turn_score"] = turn_score
        entry["state_breakdown"] = state_breakdown
        entry["turn_breakdown"] = turn_breakdown

        prev_state_breakdown = state_breakdown
        prev_state_value = state_value


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

    t_msg_idxs = _teacher_msg_indices(messages)

    # ----- Class A: per-turn-natural ----------------------------------
    # For each teacher turn, call score_turn on the prefix. Store each
    # value in the unified judge_cache under model="deterministic", turn=k.
    trajectory: list[dict[str, Any]] = []
    prev_seq_values: dict[str, float | None] = {cid: None for cid in _SEQ_DET}

    for tk, msg_idx in enumerate(t_msg_idxs):
        slice_ = messages[: msg_idx + 1]

        # Per-turn-natural: immediate reward for THIS teacher turn.
        per_turn_scores: dict[str, float | None] = {}
        for cid, mod in _PER_TURN_DET.items():
            v = mod.score_turn(slice_, task_info)
            per_turn_scores[cid] = v
            if cache is not None and not force_recall:
                store(
                    cache, cid, DETERMINISTIC_MODEL_TAG,
                    {"value": v, "rationale": ""},
                    source=f"composer:{NAME}",
                    turn=tk,
                )

        # Sequence-level: V(s_t) = score on the prefix; r_t = V_t - V_{t-1}.
        seq_state: dict[str, float | None] = {}
        seq_delta: dict[str, float | None] = {}
        for cid, mod in _SEQ_DET.items():
            v_t = mod.score(slice_, task_info)
            seq_state[cid] = v_t
            seq_delta[cid] = _delta_first_defined(prev_seq_values[cid], v_t)
            prev_seq_values[cid] = v_t
            if cache is not None and not force_recall:
                # Cache the state value V_t — that's the canonical per-turn
                # record. The delta is reproducible from the V sequence.
                store(
                    cache, cid, DETERMINISTIC_MODEL_TAG,
                    {"value": v_t, "rationale": ""},
                    source=f"composer:{NAME}",
                    turn=tk,
                )

        trajectory.append({
            "turn": tk + 1,
            "msg_idx": msg_idx,
            "scores": per_turn_scores,        # class A: per-turn immediate rewards
            "state":  seq_state,              # class B: V(s_t) for cumulative criteria
            "delta":  seq_delta,              # class B: r_t = V_t - V_{t-1}
        })

    # ----- Per-turn aggregates (state_value + turn_score) ---------------
    # Det-only running composite at each turn + delta. These are what the
    # dashboard renders per AI message.
    _annotate_state_and_turn_scores(trajectory)

    # ----- Aggregate -----------------------------------------------------
    aggregated: dict[str, float | None] = {}

    # Class A aggregate: mean of non-None per-turn values.
    for cid in _PER_TURN_DET:
        vals = [t["scores"][cid] for t in trajectory if t["scores"][cid] is not None]
        aggregated[cid] = sum(vals) / len(vals) if vals else None

    # Class B aggregate: V(s_final) — the score on the full rollout. This
    # equals the last non-None V in the trajectory; equivalently, the sum
    # of all r_t with the V_0=0 convention. We use the canonical score()
    # on the full messages for clarity.
    for cid, mod in _SEQ_DET.items():
        aggregated[cid] = mod.score(messages, task_info)
        if cache is not None and not force_recall:
            store(
                cache, cid, DETERMINISTIC_MODEL_TAG,
                {"value": aggregated[cid], "rationale": ""},
                source=f"composer:{NAME}",
                turn=None,
            )

    # ----- Class C: outcome LLM (cached) ---------------------------------
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
