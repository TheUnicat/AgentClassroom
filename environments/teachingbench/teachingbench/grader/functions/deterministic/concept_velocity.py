"""Concept velocity: steadiness of new-vocabulary introduction.

Measures: across teacher turns (in order, prose only), the per-turn
count of "novel content words" — words not seen in any prior teacher
turn and not in a small stopword set. The score reflects how *steady*
that novelty stream is across turns.

Good: a steady drip of new concepts each turn — classic scaffolding.
Bad: a big spike of new vocabulary in turn 1 followed by zero novelty
in later turns (an info-dump followed by recap-only), or wild swings
that suggest the teacher is improvising rather than pacing.

Metric: coefficient of variation of per-turn novelty counts:
    CoV = stdev(novelty) / mean(novelty)
- CoV <= 0.5  -> 1.0  (steady ramp)
- CoV >= 2.0  -> 0.0  (extreme spike-flat or chaotic pacing)
- linear in between

Notes:
- Stopwords are a small inline list (extremely common English function
  words). This is intentionally narrow; we want a quick filter, not a
  linguistic-grade list. "Content word" here is just "non-stopword
  alphabetic token of length >= 2".
- Code is stripped before tokenization. Variable names and code symbols
  shouldn't count as new vocabulary.
- Returns None if < 2 teacher turns (no variation to measure) or if
  mean novelty is 0 across all turns (degenerate: the teacher never
  introduces a single content word — almost certainly empty / trivial).
"""

from __future__ import annotations

import math

from teachingbench.grader.functions.deterministic._utils import (
    clamp01,
    strip_code_blocks,
    teacher_turns,
    words,
)


_STOPWORDS = frozenset(
    """
    a an the and or but if then else of in on at by to from for with
    is are was were be been being am do does did doing have has had
    having i you he she it we they me him her us them my your his hers
    its our their this that these those there here as so not no yes
    can could should would may might will shall just very also too
    about into over under up down out off than which who whom whose
    what when where why how
    one two three first second other some any all each every most more
    less few many much such own same other another
    """.split()
)


def _content_tokens(text: str) -> list[str]:
    out = []
    for w in words(text):
        if len(w) < 2:
            continue
        if w in _STOPWORDS:
            continue
        # numeric-only tokens aren't vocabulary
        if w.isdigit():
            continue
        out.append(w)
    return out


def score(messages: list[dict], task_info: dict) -> float | None:
    turns = teacher_turns(messages)
    if len(turns) < 2:
        return None

    seen: set[str] = set()
    novelty: list[int] = []
    for t in turns:
        toks = _content_tokens(strip_code_blocks(t))
        new = [w for w in toks if w not in seen]
        # count unique novel words in this turn, not every occurrence
        unique_new = set(new)
        novelty.append(len(unique_new))
        seen.update(unique_new)

    mean = sum(novelty) / len(novelty)
    if mean == 0:
        return None
    var = sum((n - mean) ** 2 for n in novelty) / len(novelty)
    stdev = math.sqrt(var)
    cov = stdev / mean

    # 1.0 at cov<=0.5, 0.0 at cov>=2.0
    if cov <= 0.5:
        return 1.0
    if cov >= 2.0:
        return 0.0
    return clamp01(1.0 - (cov - 0.5) / 1.5)


if __name__ == "__main__":
    steady = [
        {"role": "user", "content": "teach me pointers"},
        {"role": "assistant", "content": "Pointers store memory addresses. Variables sit in memory."},
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "Dereferencing reads the value at an address."},
        {"role": "user", "content": "and?"},
        {"role": "assistant", "content": "Arithmetic on pointers walks through arrays. Allocation gives heap memory."},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "Null pointers signal absence. Dangling pointers reference freed regions."},
    ]
    spike = [
        {"role": "user", "content": "teach me pointers"},
        {
            "role": "assistant",
            "content": (
                "Pointers, references, dereferencing, arithmetic, allocation, "
                "deallocation, null, dangling, heap, stack, segmentation, "
                "fault, malloc, free, calloc, realloc, sizeof, void, casting, "
                "alignment, padding, virtual, physical, page, table."
            ),
        },
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "Right, pointers."},
        {"role": "user", "content": "and?"},
        {"role": "assistant", "content": "Pointers, again."},
    ]
    single_turn = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Pointers store addresses."},
    ]
    print("steady     ->", score(steady, {}))
    print("spike-flat ->", score(spike, {}))
    print("1 turn     ->", score(single_turn, {}))
