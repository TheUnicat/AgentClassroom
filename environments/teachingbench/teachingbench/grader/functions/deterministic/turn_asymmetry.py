"""Turn asymmetry: teacher / student word ratio per pair.

Measures: how much more prose the teacher writes than the student does
in the immediately preceding turn. The first teacher turn pairs with
the seed question.

This benchmark caps student replies at ~50 words by design (see the
student system prompt), so teacher/student ratios are naturally higher
than in unconstrained tutoring. The earlier symmetric-tent calibration
(peak=3.5×, zero at 7×) bottomed out at 0.0 for almost every rollout
once student replies dropped below 30 words and teachers wrote 200-500.

New shape: monotonic smooth decay using `sqrt(healthy / ratio)`.
- ratio ≤ HEALTHY (= 4×) → 1.0 (plateau)
- ratio > HEALTHY → `sqrt(HEALTHY / ratio)`  (continuous at the kink)

Concretely:
    ratio = 4   → 1.000
    ratio = 6   → 0.816
    ratio = 8   → 0.707
    ratio = 12  → 0.577
    ratio = 16  → 0.500
    ratio = 25  → 0.400
    ratio = 64  → 0.250

This rewards healthy-or-below ratios fully and decays gracefully at
extremes — no cliff, no zero-floor surprises.

We score-per-pair and average the per-pair scores, rather than
averaging the ratios and scoring the mean. That way a single
wall-of-text turn doesn't drag an otherwise-balanced session to 0:
three healthy turns + one 50× turn averages to ~0.81 (good with
caveat), not 0.28 (broken). Code blocks are stripped from teacher
text — we measure prose volume, not example code volume.

Returns None when there are no teacher/student pairs.
"""

from __future__ import annotations

import math

from teachingbench.grader.functions.deterministic._utils import (
    seed_question,
    strip_code_blocks,
    word_count,
)


HEALTHY_RATIO = 4.0


def _role(m: object) -> str:
    if isinstance(m, dict):
        return str(m.get("role", ""))
    return str(getattr(m, "role", ""))


def _content(m: object) -> str:
    if isinstance(m, dict):
        c = m.get("content", "")
    else:
        c = getattr(m, "content", "")
    if isinstance(c, list):
        parts = []
        for p in c:
            if isinstance(p, dict):
                t = p.get("text") or p.get("content")
                if t:
                    parts.append(str(t))
        return "\n".join(parts)
    return str(c or "")


def _per_pair(ratio: float) -> float:
    if ratio <= HEALTHY_RATIO:
        return 1.0
    return math.sqrt(HEALTHY_RATIO / ratio)


def score(messages: list[dict], task_info: dict) -> float | None:
    seed = seed_question(messages)
    last_student: str = seed
    pairs: list[tuple[str, str]] = []
    for m in messages:
        r = _role(m)
        if r == "user":
            text = _content(m).strip()
            if not text or (text.startswith("[Session ended:") and text.endswith("]")):
                continue
            last_student = text
        elif r == "assistant":
            text = _content(m)
            if not text:
                continue
            pairs.append((last_student, text))

    if not pairs:
        return None

    per_turn_scores: list[float] = []
    for s_text, t_text in pairs:
        t_words = word_count(strip_code_blocks(t_text))
        s_words = max(word_count(s_text), 1)
        per_turn_scores.append(_per_pair(t_words / s_words))

    return sum(per_turn_scores) / len(per_turn_scores)


def score_turn(messages: list[dict], task_info: dict) -> float | None:
    """Teacher/student word ratio for the latest teacher+student pair."""
    seed = seed_question(messages)
    last_student: str = seed
    last_pair: tuple[str, str] | None = None
    for m in messages:
        r = _role(m)
        if r == "user":
            text = _content(m).strip()
            if not text or (text.startswith("[Session ended:") and text.endswith("]")):
                continue
            last_student = text
        elif r == "assistant":
            text = _content(m)
            if not text:
                continue
            last_pair = (last_student, text)
    if last_pair is None:
        return None
    s_text, t_text = last_pair
    t_words = word_count(strip_code_blocks(t_text))
    s_words = max(word_count(s_text), 1)
    return _per_pair(t_words / s_words)


if __name__ == "__main__":
    # Healthy ratios across all turns
    balanced = [
        {"role": "user", "content": "What is a pointer in C and how is it different from an integer variable?"},
        {"role": "assistant", "content": "A pointer holds a memory address rather than a plain value. The type tells the compiler how to interpret what lives at that address, and how many bytes to step when you do pointer arithmetic on it."},
        {"role": "user", "content": "And what about references in C++?"},
        {"role": "assistant", "content": "A reference is an alias for an existing variable. Once bound, it cannot be made to refer to something else, and it cannot be null."},
    ]
    # Pervasive firehose
    firehose = [
        {"role": "user", "content": "Pointers?"},
        {"role": "assistant", "content": "A pointer is a variable. " * 60},
    ]
    # Three healthy turns + one outlier wall-of-text — score-then-average
    # should keep this comfortably above 0.5
    mostly_ok = [
        {"role": "user", "content": "Explain a pointer."},
        {"role": "assistant", "content": "A pointer stores a memory address. " * 4},
        {"role": "user", "content": "And dereferencing?"},
        {"role": "assistant", "content": "Dereferencing reads the value at that address. " * 4},
        {"role": "user", "content": "Got it"},
        {"role": "assistant", "content": "Memory diagrams help here. " * 4},
        {"role": "user", "content": "ok"},
        {"role": "assistant", "content": "Now let me dump everything: " + ("pointer arithmetic and alignment and the stack and heap layouts. " * 40)},
    ]
    print("balanced  ->", round(score(balanced, {}), 3))
    print("firehose  ->", round(score(firehose, {}), 3))
    print("mostly_ok ->", round(score(mostly_ok, {}), 3))
