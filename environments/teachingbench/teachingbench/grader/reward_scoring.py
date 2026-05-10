"""Composite-reward formula for TeachingBench.

THIS FILE IS WHERE THE REWARD SCORING FORMULA LIVES.

Edit the constants and/or the `compute_composite` function below to change
how per-criterion judge scores combine into the final [0, 1] reward. The
formula version + parameters are logged in every trial's `judge_breakdown`,
so post-hoc analysis can see what produced any given composite — and if we
ever want to re-tune, we can recompute over saved scores.

Output is guaranteed in [0, 1] by clipping. The pre-clip raw value is also
returned + logged so clipping behaviour is visible.

Design principles:
- Each criterion contribution is in [0, 1], weights sum to 1 → base in [0, 1].
- Penalties subtract; their max magnitude is bounded by the constant
  multipliers below. If the sum of (base + penalties + bonuses) ever leaves
  [0, 1], we clip.
- The pre-clip value is preserved as `composite_raw` for inspection.
"""

from __future__ import annotations

from typing import Any

# ====================================================================
# TUNABLE CONSTANTS — edit these to retune the reward shape.
# Bump FORMULA_VERSION whenever you change the math or these constants.
# ====================================================================

FORMULA_VERSION = "v1-soft-gate-on-answers"

# Soft gate: linear penalty when answers_the_question drops below threshold.
#   penalty = SOFT_GATE_WEIGHT * max(0, SOFT_GATE_THRESHOLD - score)
# Max penalty = SOFT_GATE_WEIGHT * SOFT_GATE_THRESHOLD (clipped after).
SOFT_GATE_CRITERION = "answers_the_question"
SOFT_GATE_THRESHOLD = 0.3
SOFT_GATE_WEIGHT = 1.0

# ====================================================================
# THE FORMULA. Reads like prose; edit freely.
# ====================================================================


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
        composite_raw:    pre-clip value (can be < 0 or > 1)
        terms:            named intermediate values (base, penalties, etc.)
        formula_version:  copy of FORMULA_VERSION for logging
        formula_params:   copy of the tunable constants for logging
    """
    # Step 1: weighted average of non-null criteria. Null criteria are
    # skipped and their weight share is renormalized across the others
    # (so a single null doesn't deflate the base score).
    active = [(cid, scores[cid], weights[cid])
              for cid in scores
              if isinstance(scores[cid], (int, float))]
    total_w = sum(w for _, _, w in active)
    base = sum(v * w for _, v, w in active) / total_w if total_w > 0 else 0.0

    # Step 2: soft gate. If the tutor failed to answer the question,
    # subtract a linear penalty. Threshold + weight live in the constants
    # above. When the criterion is null (uncommon for answers_the_question),
    # no penalty applies.
    q = scores.get(SOFT_GATE_CRITERION)
    if isinstance(q, (int, float)):
        gate_penalty = SOFT_GATE_WEIGHT * max(0.0, SOFT_GATE_THRESHOLD - q)
    else:
        gate_penalty = 0.0

    # Step 3: combine + clip to [0, 1]. Log the raw value separately.
    raw = base - gate_penalty
    composite = max(0.0, min(1.0, raw))

    return {
        "composite": composite,
        "composite_raw": raw,
        "terms": {
            "base_weighted_sum": base,
            "gate_penalty": gate_penalty,
        },
        "formula_version": FORMULA_VERSION,
        "formula_params": {
            "soft_gate_criterion": SOFT_GATE_CRITERION,
            "soft_gate_threshold": SOFT_GATE_THRESHOLD,
            "soft_gate_weight": SOFT_GATE_WEIGHT,
        },
    }


def describe() -> dict[str, Any]:
    """Human-readable formula description for logging / dashboards."""
    return {
        "version": FORMULA_VERSION,
        "expression": (
            f"clip( weighted_sum(scores) - "
            f"{SOFT_GATE_WEIGHT} * max(0, {SOFT_GATE_THRESHOLD} - "
            f"{SOFT_GATE_CRITERION}), 0, 1 )"
        ),
        "params": {
            "soft_gate_criterion": SOFT_GATE_CRITERION,
            "soft_gate_threshold": SOFT_GATE_THRESHOLD,
            "soft_gate_weight": SOFT_GATE_WEIGHT,
        },
    }
