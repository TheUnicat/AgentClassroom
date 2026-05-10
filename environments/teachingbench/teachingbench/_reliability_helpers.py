"""Shared helpers for `judge_reliability_check` and `task_reliability_check`.

Stats math + per-criterion table printer. Kept private (`_`-prefixed) — these are
implementation details of the two check scripts, not a public API.
"""

from __future__ import annotations

import statistics
from typing import Any


def stats_for(values: list[float]) -> dict[str, float]:
    """Return min / max / range / median / mean / stdev / cv. Empty input → {}."""
    if not values:
        return {}
    out = {
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
        "median": statistics.median(values),
        "mean": statistics.fmean(values),
    }
    if len(values) >= 2:
        sd = statistics.stdev(values)
        out["stdev"] = sd
        out["cv"] = sd / out["mean"] if out["mean"] > 0 else 0.0
    else:
        out["stdev"] = 0.0
        out["cv"] = 0.0
    return out


def print_reliability_table(
    *,
    title: str,
    context_lines: list[str],
    criterion_ids: list[str],
    per_trial_scores: list[dict[str, float | None]],
    per_trial_composites: list[float],
    n: int,
    errors: list[str] | None = None,
) -> None:
    """Print a uniform reliability table.

    Args:
        title: Header (e.g., "Judge reliability — n=8").
        context_lines: Lines printed under the title (task, topic, etc.).
        criterion_ids: Order to print criteria in (matches the rubric).
        per_trial_scores: One dict per trial, keyed by criterion id; values are
            float in [0, 1] or None.
        per_trial_composites: One composite per trial (floats).
        n: The intended trial count (for the "scored x/n" column).
        errors: Optional list of trial-level error messages to print below the table.
    """
    print()
    print(f"=== {title} ===")
    for line in context_lines:
        print(line)
    print()

    cols = [
        ("criterion", 16),
        ("scored", 8),
        ("min", 7),
        ("max", 7),
        ("range", 7),
        ("median", 7),
        ("mean", 7),
        ("stdev", 7),
        ("CV", 7),
    ]
    print("  ".join(label.ljust(w) for label, w in cols))
    print("  ".join("-" * w for _, w in cols))

    for cid in criterion_ids:
        per_trial = [t.get(cid) for t in per_trial_scores]
        nums = [v for v in per_trial if isinstance(v, (int, float))]
        if not nums:
            row = [cid, f"0/{n}", "—", "—", "—", "—", "—", "—", "—"]
        else:
            s = stats_for(nums)
            row = [
                cid,
                f"{len(nums)}/{n}",
                f"{s['min']:.3f}",
                f"{s['max']:.3f}",
                f"{s['range']:.3f}",
                f"{s['median']:.3f}",
                f"{s['mean']:.3f}",
                f"{s['stdev']:.3f}",
                f"{s['cv']:.3f}",
            ]
        print("  ".join(str(cell).ljust(w) for cell, (_, w) in zip(row, cols)))

    print("  ".join("-" * w for _, w in cols))
    if per_trial_composites:
        s = stats_for(per_trial_composites)
        row = [
            "composite",
            f"{len(per_trial_composites)}/{n}",
            f"{s['min']:.3f}",
            f"{s['max']:.3f}",
            f"{s['range']:.3f}",
            f"{s['median']:.3f}",
            f"{s['mean']:.3f}",
            f"{s['stdev']:.3f}",
            f"{s['cv']:.3f}",
        ]
        print("  ".join(str(cell).ljust(w) for cell, (_, w) in zip(row, cols)))

    if errors:
        print()
        print(f"WARNING: {len(errors)}/{n} trials reported errors.")
        for i, e in enumerate(errors):
            print(f"  trial {i}: {e}")

    print()
    print("Interpretation:")
    print("  CV (coefficient of variation = stdev/mean) is the main reliability dial.")
    print("  CV < 0.05  → very stable.")
    print("  CV 0.05..0.15 → acceptable for relative ranking; treat absolute values cautiously.")
    print("  CV > 0.15  → noisy; tighten rubric anchors / lower temperature / try a different model.")
