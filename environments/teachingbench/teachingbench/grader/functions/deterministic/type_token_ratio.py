"""Type-token ratio: vocabulary diversity across teacher prose.

Measures: lexical diversity of the teacher's prose after stripping
code, computed as MATTR (moving-average TTR over 100-word windows) for
length-stability.

Empirically (on the v0.1 benchmark's 4-turn rollouts at SOTA quality),
MATTR sits in **[0.60, 0.80]** across nano / mini / gpt-5.4 / opus —
technical prose has lots of unique terminology so the rate of new
words per 100-word window is high. The earlier tent (peak=0.45,
half=0.30) cliffed to 0.0 above MATTR=0.75, which marked four out of
five sample rollouts as catastrophic — clearly a calibration error
rather than real signal.

New shape: a smooth piecewise function with a *wide* plateau in the
"normal technical prose" zone and gentle penalties at the extremes.
- MATTR ≤ 0.10              → 0.0   (genuine vocabulary loop)
- MATTR ∈ [0.10, 0.40]      → linear ramp 0 → 1
- MATTR ∈ [0.40, 0.65]      → 1.0   (plateau)
- MATTR ∈ [0.65, 0.95]      → linear decline 1.0 → 0.7
- MATTR ≥ 0.95              → 0.7   (asymptote — jargon dump)

Concretely:
    MATTR = 0.30 → 0.667
    MATTR = 0.40 → 1.000  (plateau start)
    MATTR = 0.55 → 1.000
    MATTR = 0.65 → 1.000  (plateau end)
    MATTR = 0.75 → 0.900
    MATTR = 0.85 → 0.800
    MATTR = 0.95 → 0.700

Length guard: raw TTR is sensitive to total length (a short text
trivially has high TTR; a long text trivially has lower TTR). The
MATTR window normalizes this, but we still need a floor: if the
teacher writes fewer than 100 prose-words total, return None — the
single-window estimate is too noisy to score.

Returns None when there are no teacher turns at all or when total
prose-words < 100.
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    strip_code_blocks,
    teacher_turns,
    words,
)


WINDOW = 100
PARTIAL_TAIL_MIN = 50  # drop trailing window if shorter

LOW_ZERO = 0.10
LOW_PLATEAU = 0.40
HIGH_PLATEAU = 0.65
HIGH_FLOOR = 0.95
FLOOR_VALUE = 0.70


def _mattr(tokens: list[str]) -> float | None:
    n = len(tokens)
    if n < WINDOW:
        if n == 0:
            return None
        return len(set(tokens)) / n
    ratios: list[float] = []
    i = 0
    while i + WINDOW <= n:
        chunk = tokens[i : i + WINDOW]
        ratios.append(len(set(chunk)) / WINDOW)
        i += WINDOW
    tail = tokens[i:]
    if len(tail) >= PARTIAL_TAIL_MIN:
        ratios.append(len(set(tail)) / len(tail))
    return sum(ratios) / len(ratios)


def _shape(mattr: float) -> float:
    if mattr <= LOW_ZERO:
        return 0.0
    if mattr <= LOW_PLATEAU:
        # 0 at LOW_ZERO → 1 at LOW_PLATEAU
        return (mattr - LOW_ZERO) / (LOW_PLATEAU - LOW_ZERO)
    if mattr <= HIGH_PLATEAU:
        return 1.0
    if mattr <= HIGH_FLOOR:
        # 1.0 at HIGH_PLATEAU → FLOOR_VALUE at HIGH_FLOOR
        span = HIGH_FLOOR - HIGH_PLATEAU
        drop = 1.0 - FLOOR_VALUE
        return 1.0 - (mattr - HIGH_PLATEAU) / span * drop
    return FLOOR_VALUE


def score(messages: list[dict], task_info: dict) -> float | None:
    turns = teacher_turns(messages)
    if not turns:
        return None
    prose = "\n\n".join(strip_code_blocks(t) for t in turns)
    toks = words(prose)
    if len(toks) < WINDOW:
        return None
    mattr = _mattr(toks)
    if mattr is None:
        return None
    return _shape(mattr)


if __name__ == "__main__":
    # Normal technical prose — MATTR ~0.7+ on SOTA models
    coherent_body = (
        "A pointer is a value that stores the address of another value in "
        "memory. The pointer itself sits in memory like any other variable. "
        "When you read the pointer you get an address; when you dereference "
        "the pointer you get the value at that address. In C the type of a "
        "pointer tells the compiler how many bytes to read when you "
        "dereference it. A pointer to an int reads four bytes on most "
        "systems. A pointer to a char reads one byte. The pointer arithmetic "
        "rules follow from this: adding one to a pointer steps it forward "
        "by the size of its pointee, not by one byte. So an int pointer "
        "plus one moves forward by four bytes on a typical machine."
    ) * 2
    # Near-pure repetition: low MATTR, should score low
    repetitive_body = "pointers store addresses pointers are useful in code. " * 60
    # Dense unique-word listing: high MATTR, should hit the floor
    jargon_body = (
        "homomorphism endofunctor monad comonad adjunction kan extension "
        "limit colimit terminal initial product coproduct equalizer "
        "coequalizer pullback pushout fibration cofibration cartesian "
        "closed topos sheaf presheaf yoneda lemma naturality coherence "
    ) * 3
    coherent = [{"role": "assistant", "content": coherent_body}]
    repetitive = [{"role": "assistant", "content": repetitive_body}]
    jargon = [{"role": "assistant", "content": jargon_body}]
    too_short = [{"role": "assistant", "content": "A pointer holds an address."}]
    print("coherent   ->", round(score(coherent, {}) or 0, 3))
    print("repetitive ->", round(score(repetitive, {}) or 0, 3))
    print("jargon     ->", round(score(jargon, {}) or 0, 3))
    print("too short  ->", score(too_short, {}))

    # Direct shape probe
    print()
    print("  shape probe (MATTR → score):")
    for m in (0.05, 0.10, 0.20, 0.30, 0.40, 0.55, 0.65, 0.75, 0.85, 0.95, 1.00):
        print(f"    MATTR={m:.2f} -> {_shape(m):.3f}")
