"""Type-token ratio: vocabulary diversity across teacher prose.

Measures: lexical diversity of the teacher's prose, after stripping
code. TTR = unique_tokens / total_tokens.

Good: ~0.45 — varied but coherent. Words repeat enough to maintain a
consistent topic; new words appear often enough that the teacher isn't
looping a small phrase set.
Bad (low TTR, ~< 0.15): the teacher is repeating themselves — a stuck
loop or oversimplified parroting.
Bad (high TTR, ~> 0.75): the teacher is jargon-dumping without enough
repetition to form a coherent thread.

Score: tent kernel centered at 0.45 with half_width 0.30 — so:
    TTR = 0.45 -> 1.0
    TTR = 0.15 -> 0.0
    TTR = 0.75 -> 0.0
    linear between.

CRITICAL: raw TTR is sensitive to total length. A short text trivially
has high TTR (every word is new); a long text trivially has lower TTR
(common words repeat). So:
    - < 100 words total prose         -> None (unreliable, skip)
    - 100 <= total < 1000 words       -> moving-window TTR
    - >= 1000 words                   -> moving-window TTR
Window size = 100 words; we slide non-overlapping windows over the
concatenated teacher prose and take the mean of per-window TTRs. The
last partial window (< 50 words) is dropped to avoid noise. This is
called "MATTR" (moving-average TTR) in the corpus-linguistics
literature; standard fix for length-sensitivity.

Returns None when there are no teacher turns at all.
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    strip_code_blocks,
    teacher_turns,
    tent,
    words,
)


PEAK = 0.45
HALF_WIDTH = 0.30
WINDOW = 100
PARTIAL_TAIL_MIN = 50  # drop trailing window if shorter than this


def _mattr(tokens: list[str]) -> float | None:
    n = len(tokens)
    if n < WINDOW:
        # not enough for even one window; fall back to raw
        if n == 0:
            return None
        return len(set(tokens)) / n
    ratios: list[float] = []
    i = 0
    while i + WINDOW <= n:
        chunk = tokens[i : i + WINDOW]
        ratios.append(len(set(chunk)) / WINDOW)
        i += WINDOW
    # handle tail
    tail = tokens[i:]
    if len(tail) >= PARTIAL_TAIL_MIN:
        ratios.append(len(set(tail)) / len(tail))
    return sum(ratios) / len(ratios)


def score(messages: list[dict], task_info: dict) -> float | None:
    turns = teacher_turns(messages)
    if not turns:
        return None
    prose = "\n\n".join(strip_code_blocks(t) for t in turns)
    toks = words(prose)
    if len(toks) < 100:
        return None
    ttr = _mattr(toks)
    if ttr is None:
        return None
    return tent(ttr, peak=PEAK, half_width=HALF_WIDTH)


if __name__ == "__main__":
    # "coherent" — natural prose with sentence-level repetition (function words,
    # topic words recurring): aim for MATTR ~0.45.
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
    # near-pure repetition — TTR should crater toward 0
    repetitive_body = "pointers store addresses pointers are useful in code. " * 60
    # dense unique-word listing — high MATTR, score should drop
    jargon_body = (
        "homomorphism endofunctor monad comonad adjunction kan extension "
        "limit colimit terminal initial product coproduct equalizer "
        "coequalizer pullback pushout fibration cofibration cartesian "
        "closed topos sheaf presheaf yoneda lemma naturality coherence "
        "associator unitor pentagon triangle braided symmetric monoidal "
        "tensor compact rigid dualizable trace dimension character "
        "modulus residue ideal radical spectrum scheme variety morphism "
        "isomorphism epimorphism monomorphism kernel image cokernel "
    ) * 3
    coherent = [{"role": "assistant", "content": coherent_body}]
    repetitive = [{"role": "assistant", "content": repetitive_body}]
    jargon = [{"role": "assistant", "content": jargon_body}]
    too_short = [{"role": "assistant", "content": "A pointer holds an address."}]
    print("coherent   ->", score(coherent, {}))
    print("repetitive ->", score(repetitive, {}))
    print("jargon     ->", score(jargon, {}))
    print("too short  ->", score(too_short, {}))
