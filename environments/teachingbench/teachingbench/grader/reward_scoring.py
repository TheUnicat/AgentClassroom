"""Composite-reward formula for TeachingBench.

THIS FILE IS WHERE THE COMPOSITE FORMULA LIVES.

Edit the constants and/or the `compute_composite` function below to change
how per-criterion judge scores combine into the final [0, 1] reward. The
formula version + parameters are logged in every trial's `judge_breakdown`,
so post-hoc analysis can see what produced any given composite — and if we
ever want to re-tune, we can recompute over saved scores.

Output is guaranteed in [0, 1] by clipping. The pre-clip raw value is also
returned + logged so clipping behaviour is visible.

============================================================================
Current formula (v3):

  1. Each non-null criterion score is **convex-transformed** below the kink:
        score'  =  score                       if score >= LOW_SCORE_KINK
                   score**POWER / KINK**(POWER-1)   if score <  LOW_SCORE_KINK
     With KINK=0.5, POWER=2 this is `score² / 0.5 = 2·score²` below 0.5 and
     a no-op above 0.5. Continuous at the kink. So 0.3 contributes 0.18,
     0.1 contributes 0.02, but 0.7 still contributes 0.7.

  2. **Convex base** = weighted sum of TRANSFORMED scores. Null criteria are
     skipped and their weight share is renormalized across the rest.

  3. Each criterion gets a per-criterion **ceiling**, computed from the same
     transformed score (so a 0.3 judge score, "really" worth 0.18, drives the
     ceiling at 0.18 not 0.3 — consistent with the base calculation):
        t = transformed_score
        ceiling_for(t)  =  cap_at_zero  +  (1 - cap_at_zero) * (1 - (1 - t)**CEILING_POWER)
     With CEILING_POWER=2 this is REVERSE-QUADRATIC: ceiling phases in only
     near the bottom of the score range. f(0)=cap_at_zero; f(0.5)=cap+0.75·(1-cap);
     f(1)=1. So lying (transformed=0) caps composite hard at cap_at_zero; a
     moderate transformed score lets the ceiling slack back toward 1.
     Composite is bounded by MIN over per-criterion ceilings.

  4. Final = clip( min(convex_base, composite_ceiling), 0, 1 ).
============================================================================
"""

from __future__ import annotations

from typing import Any

# ====================================================================
# TUNABLE CONSTANTS — edit these to retune the reward shape.
# Bump FORMULA_VERSION whenever you change the math or these constants.
# ====================================================================

FORMULA_VERSION = "v3-convex-revquad-ceilings"

# Convex-transform: below LOW_SCORE_KINK, scores are squashed by power.
# POWER=2 (quadratic) is the default; raise it for harsher punishment of
# low scores, lower it (toward 1.0) for milder.
LOW_SCORE_KINK = 0.5
LOW_SCORE_POWER = 2.0

# Ceiling interpolation curve: ceiling(t) = cap + (1-cap) * (1 - (1-t)**POWER)
# POWER=1 → linear (aggressive at moderate scores).
# POWER=2 → reverse-quadratic (ceiling bites only near the bottom; current default).
# POWER=3 → reverse-cubic (even more lenient at moderate scores).
CEILING_INTERPOLATION_POWER = 1.7

# Per-criterion ceilings: if a criterion's transformed score is 0, the
# composite is capped at this value. Interpolated up to 1.0 at transformed
# score=1, via the reverse-quadratic curve above. Criteria not listed have
# no ceiling (cap=1.0).
#
# Interpretation: the lower the cap, the more "gating" the criterion. A
# criterion with cap=0.1 means "if you score 0 here, you cannot exceed 0.1
# on the composite, no matter how good everything else is."
PER_CRITERION_CEILING_AT_ZERO: dict[str, float] = {
    "answers_the_question":     0.20,   # most gating: wrong-question is catastrophic
    "factual_correctness":      0.10,   # load-bearing error → very bad
    "anti_firehose":            0.55,   # heavy firehose → bad presentation
    "meeting_student_level":    0.60,   # wrong-level throughout → bad presentation
    "clarity":                  0.65,   # confusing writing → real cost
    "bridging":                 0.70,   # ignoring materials → bad but task-dependent
    "scaffolding":              0.70,   # no scaffolding → fixable
    "no_excessive_validation":  0.80,   # sycophancy → annoying but doesn't ruin teaching
}


# ====================================================================
# THE FORMULA. Reads like prose; edit freely.
# ====================================================================


def _convex_below_kink(score: float) -> float:
    """Pass through if score >= KINK; otherwise convex curve through (0,0) and (KINK, KINK)."""
    if score >= LOW_SCORE_KINK:
        return score
    return (score ** LOW_SCORE_POWER) / (LOW_SCORE_KINK ** (LOW_SCORE_POWER - 1.0))


def compute_composite(
    scores: dict[str, float | None],
    weights: dict[str, float],
) -> dict[str, Any]:
    """Compute the final [0, 1] composite reward from per-criterion judge scores.

    Args:
        scores:  {criterion_id: float in [0,1] or None (= N/A)}
        weights: {criterion_id: nonneg float}  — must sum to ~1.0

    Returns a dict with:
        composite:        final reward, clipped to [0, 1]
        composite_raw:    pre-clip value (can exceed bounds)
        terms:            named intermediate values for inspection
        formula_version:  copy of FORMULA_VERSION for logging
        formula_params:   copy of the tunable constants for logging
    """
    # 1. Convex-transform each non-null criterion's score.
    transformed: dict[str, float | None] = {}
    for cid, v in scores.items():
        transformed[cid] = _convex_below_kink(v) if isinstance(v, (int, float)) else None

    # 2. Weighted sum of transformed scores, renormalized over non-null criteria.
    active = [
        (cid, transformed[cid], weights[cid])
        for cid in transformed
        if isinstance(transformed[cid], (int, float))
    ]
    total_w = sum(w for _, _, w in active)
    convex_base = sum(v * w for _, v, w in active) / total_w if total_w > 0 else 0.0

    # 3. Per-criterion ceiling, computed from the TRANSFORMED score (consistent
    #    with how that score contributes to the base) and using the
    #    reverse-quadratic curve:
    #       ceiling(t) = cap_at_zero + (1 - cap_at_zero) * (1 - (1 - t)**CEILING_POWER)
    #    At t=0 the ceiling is cap_at_zero; at t=1 it's 1.0. Phase-in is
    #    convex from above (bites at the bottom, lenient in the middle).
    composite_ceiling = 1.0
    per_criterion_ceiling: dict[str, float] = {}
    for cid in scores:
        t = transformed[cid]
        if not isinstance(t, (int, float)):
            continue
        cap0 = PER_CRITERION_CEILING_AT_ZERO.get(cid)
        if cap0 is None:
            continue
        ceiling_for_this = cap0 + (1.0 - cap0) * (1.0 - (1.0 - t) ** CEILING_INTERPOLATION_POWER)
        per_criterion_ceiling[cid] = ceiling_for_this
        if ceiling_for_this < composite_ceiling:
            composite_ceiling = ceiling_for_this

    # 4. Combine + clip to [0, 1].
    raw = min(convex_base, composite_ceiling)
    composite = max(0.0, min(1.0, raw))

    return {
        "composite": composite,
        "composite_raw": raw,
        "terms": {
            "transformed_scores": transformed,
            "convex_base": convex_base,
            "per_criterion_ceiling": per_criterion_ceiling,
            "composite_ceiling": composite_ceiling,
        },
        "formula_version": FORMULA_VERSION,
        "formula_params": {
            "low_score_kink": LOW_SCORE_KINK,
            "low_score_power": LOW_SCORE_POWER,
            "ceiling_interpolation_power": CEILING_INTERPOLATION_POWER,
            "per_criterion_ceiling_at_zero": dict(PER_CRITERION_CEILING_AT_ZERO),
        },
    }


def describe() -> dict[str, Any]:
    """Human-readable formula description for logging / dashboards."""
    return {
        "version": FORMULA_VERSION,
        "expression": (
            f"clip( min( "
            f"weighted_sum(t_i),  "
            f"min_over_i( cap0_i + (1 - cap0_i) * (1 - (1 - t_i)**{CEILING_INTERPOLATION_POWER}) ) "
            f"), 0, 1 )  "
            f"where t_i = convex_below_kink(score_i, kink={LOW_SCORE_KINK}, power={LOW_SCORE_POWER})"
        ),
        "params": {
            "low_score_kink": LOW_SCORE_KINK,
            "low_score_power": LOW_SCORE_POWER,
            "ceiling_interpolation_power": CEILING_INTERPOLATION_POWER,
            "per_criterion_ceiling_at_zero": dict(PER_CRITERION_CEILING_AT_ZERO),
        },
    }
