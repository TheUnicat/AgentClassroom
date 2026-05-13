"""Flesch-Kincaid Grade Level vs difficulty band.

Measures: readability of the teacher's prose (code stripped), expressed
as a US grade level, scored against the band that's appropriate for the
task's stated difficulty.

Good: prose pitched to the student's level. An absolute_beginner should
get plain-English text (FK ~6-9). An expert can take denser writing.
Bad: a teacher writing at FK 14 for an absolute_beginner is a jargon
dump; a teacher writing at FK 5 for an expert is condescending and
information-starved.

FK formula:
    0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59

Syllable estimation is a vowel-group heuristic (not a perfect estimator;
that's fine — we're scoring a band, not a precise grade level):
    - count maximal runs of [aeiouy] per word, minimum 1
    - subtract 1 for a trailing silent 'e' (when word > 3 letters and the
      e is not the only vowel)

Sentence count: split on [.!?]+ followed by whitespace or end-of-string;
empty splits ignored. This undercounts slightly on sentences ending mid-
word (rare) and overcounts on lists like "1. foo 2. bar" but the noise
washes out at paragraph scale.

Bands (target FK range for difficulty):
    absolute_beginner -> 6-9
    beginner          -> 7-10
    intermediate      -> 9-12
    advanced          -> 11-14
    expert            -> 12-16
    (unknown/missing) -> 9-12

Score: 1.0 inside the band, linear decay to 0.0 at 4 grade levels
outside (either above or below the band). Returning None when there's
not enough text to compute meaningfully (<20 words or <2 sentences) or
no teacher turns at all.

**LaTeX handling.** Math content fools the raw FK formula: LaTeX
tokenizes into many short symbol "words" (`x`, `n`, `frac`, `lim`),
which inflate words/sentence and crash syllables/word, dragging the
estimate to 9-12 even when the prose around the math is dense. Fix:

  1. Measure latex_density on the post-code-strip text (chars inside
     LaTeX / total chars).
  2. Strip LaTeX before computing the base FK on the surrounding prose.
  3. Add `LATEX_FK_BUMP * latex_density` to the base — treats LaTeX
     content as "somewhat above-average complexity". A response that's
     ~30% LaTeX (typical math tutoring) gets ~+1.2 grade levels.
  4. If after stripping there's too little prose to FK but there WAS
     significant LaTeX, fall back to `LATEX_FALLBACK_FK = 13` (advanced
     band) — pure-equation responses register as graduate-level dense.
"""

from __future__ import annotations

import re

from teachingbench.grader.functions.deterministic._utils import (
    clamp01,
    latex_density as _latex_density,
    strip_code_blocks,
    strip_latex,
    teacher_turns,
    words,
)


_BANDS: dict[str, tuple[float, float]] = {
    "absolute_beginner": (6.0, 9.0),
    "beginner": (7.0, 10.0),
    "intermediate": (9.0, 12.0),
    "advanced": (11.0, 14.0),
    "expert": (12.0, 16.0),
}
_DEFAULT_BAND = (9.0, 12.0)
_OUTSIDE_DECAY_GRADES = 4.0

# LaTeX as "somewhat above-average complexity". A response that's e.g.
# 30% LaTeX by chars gets +1.2 grades on top of its base prose FK.
LATEX_FK_BUMP = 4.0
# Fallback when the response is mostly equations (prose too short to FK)
# AND latex_density is significant. 13.0 is mid-advanced — not catastrophic,
# but signals "this is graduate-level dense" for tasks below that band.
LATEX_FALLBACK_FK = 13.0
LATEX_FALLBACK_MIN_DENSITY = 0.15

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+(?:\s+|$)")
_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+")


def _count_syllables(word: str) -> int:
    w = word.lower()
    groups = len(_VOWEL_GROUP_RE.findall(w))
    if groups == 0:
        return 1
    # silent trailing 'e' (only if word has another vowel group earlier)
    if len(w) > 3 and w.endswith("e") and groups > 1:
        # only deduct if the 'e' is itself a standalone vowel group
        # (i.e. preceded by a consonant), which the regex guarantees
        groups -= 1
    return max(1, groups)


def _sentence_count(text: str) -> int:
    parts = _SENTENCE_SPLIT_RE.split(text)
    return sum(1 for p in parts if p.strip())


def _fk_grade(text: str) -> float | None:
    toks = words(text)
    n_words = len(toks)
    n_sents = _sentence_count(text)
    if n_words < 20 or n_sents < 2:
        return None
    n_syll = sum(_count_syllables(w) for w in toks)
    return 0.39 * (n_words / n_sents) + 11.8 * (n_syll / n_words) - 15.59


def _band_for(task_info: dict) -> tuple[float, float]:
    diff = (task_info or {}).get("difficulty")
    if isinstance(diff, str):
        return _BANDS.get(diff.strip().lower(), _DEFAULT_BAND)
    return _DEFAULT_BAND


def score(messages: list[dict], task_info: dict) -> float | None:
    turns = teacher_turns(messages)
    if not turns:
        return None
    prose = "\n\n".join(strip_code_blocks(t) for t in turns)
    density = _latex_density(prose)
    clean = strip_latex(prose)
    base = _fk_grade(clean)
    if base is None:
        # Too little prose to compute base FK. If there was significant
        # LaTeX, the response was a math-block; rate it as dense (advanced
        # band). Otherwise we genuinely have nothing to score.
        if density >= LATEX_FALLBACK_MIN_DENSITY:
            fk = LATEX_FALLBACK_FK
        else:
            return None
    else:
        fk = base + LATEX_FK_BUMP * density
    lo, hi = _band_for(task_info)
    if lo <= fk <= hi:
        return 1.0
    if fk < lo:
        dist = lo - fk
    else:
        dist = fk - hi
    return clamp01(1.0 - dist / _OUTSIDE_DECAY_GRADES)


def score_turn(messages: list[dict], task_info: dict) -> float | None:
    """FK band-fit for only the most recent teacher turn."""
    turns = teacher_turns(messages)
    if not turns:
        return None
    prose = strip_code_blocks(turns[-1])
    density = _latex_density(prose)
    clean = strip_latex(prose)
    base = _fk_grade(clean)
    if base is None:
        if density >= LATEX_FALLBACK_MIN_DENSITY:
            fk = LATEX_FALLBACK_FK
        else:
            return None
    else:
        fk = base + LATEX_FK_BUMP * density
    lo, hi = _band_for(task_info)
    if lo <= fk <= hi:
        return 1.0
    dist = lo - fk if fk < lo else fk - hi
    return clamp01(1.0 - dist / _OUTSIDE_DECAY_GRADES)


if __name__ == "__main__":
    # mid-grade prose, FK roughly in the 8-11 range
    mid = [
        {"role": "user", "content": "What is recursion?"},
        {
            "role": "assistant",
            "content": (
                "Recursion happens when a function calls itself to solve a "
                "smaller version of the same problem. Each call works on a "
                "smaller input until you reach a base case, which returns "
                "without calling again. After that, the partial results "
                "combine back up the chain. Recursive solutions often look "
                "shorter than loops, but they use extra stack memory because "
                "every call leaves a frame behind until it returns. A good "
                "exercise is computing a factorial both ways and comparing "
                "the call stack at the deepest point."
            ),
        },
    ]
    dense = [
        {"role": "user", "content": "Explain monads."},
        {
            "role": "assistant",
            "content": (
                "Monads constitute a fundamental categorical abstraction "
                "encapsulating sequential composition of effectful computations "
                "via endofunctorial unit and multiplication transformations "
                "satisfying associativity and identity coherence diagrams. "
                "Specifically, a monad on a category C comprises a triple "
                "consisting of an endofunctor together with two natural "
                "transformations exhibiting structural coherence properties."
            ),
        },
    ]
    too_short = [
        {"role": "user", "content": "Hi"},
        {"role": "assistant", "content": "Hi there."},
    ]
    print("mid prose, intermediate band      ->", score(mid, {"difficulty": "intermediate"}))
    print("mid prose, expert band            ->", score(mid, {"difficulty": "expert"}))
    print("dense prose, expert band          ->", score(dense, {"difficulty": "expert"}))
    print("dense prose, absolute_beginner    ->", score(dense, {"difficulty": "absolute_beginner"}))
    print("too short                         ->", score(too_short, {"difficulty": "beginner"}))
    print("empty                             ->", score([], {}))
