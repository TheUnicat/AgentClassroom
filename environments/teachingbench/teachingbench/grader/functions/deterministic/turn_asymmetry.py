"""Turn asymmetry: teacher / student word ratio per pair.

Measures: how much more prose the teacher writes than the student does
in the immediately preceding turn. The first teacher turn is paired
with the seed question.

Good: teacher writes ~2-5x student. Enough to actually explain, not so
much that the student is being lectured at. We peak at 3.5x.
Bad too low: ratio < ~1 means the teacher is being terser than the
student — under-explaining, or just rubber-stamping.
Bad too high: ratio > ~7 means each student sentence triggers a
multi-paragraph teacher response — info-dumping.

Code blocks are stripped from teacher text (we want prose volume, not
fenced examples). Student text is left as-is — students don't typically
paste code dumps, and if they do we want their question to "count" the
same.

Per-pair ratio is clamped at 20 before averaging so one extreme outlier
(student says "ok", teacher writes 600 words) can't drag the mean off
the tent function entirely.

Mapping: `tent(mean_ratio, peak=3.5, half_width=3.5)` — value of 1.0 at
3.5x, linear drop to 0.0 at 0x and at 7x.

Returns None when there are no teacher/student pairs (no teacher turns,
or no seed question and no other student turns).
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    seed_question,
    strip_code_blocks,
    tent,
    word_count,
)


PEAK = 3.5
HALF_WIDTH = 3.5
MAX_RATIO = 20.0


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


def score(messages: list[dict], task_info: dict) -> float | None:
    # Pair each assistant turn with the most recent prior student turn,
    # falling back to the seed question for the opener.
    seed = seed_question(messages)
    last_student: str = seed
    pairs: list[tuple[str, str]] = []  # (student_text, teacher_text)
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

    ratios: list[float] = []
    for s_text, t_text in pairs:
        t_words = word_count(strip_code_blocks(t_text))
        s_words = max(word_count(s_text), 1)
        ratios.append(min(t_words / s_words, MAX_RATIO))

    mean_ratio = sum(ratios) / len(ratios)
    return tent(mean_ratio, peak=PEAK, half_width=HALF_WIDTH)


if __name__ == "__main__":
    # Case 1: healthy ratio — teacher writes ~3-4x student.
    balanced = [
        {"role": "user", "content": "What is a pointer in C and how is it different from an integer variable?"},  # 14
        {"role": "assistant", "content": "A pointer holds a memory address rather than a plain value. The type tells the compiler how to interpret what lives at that address, and how many bytes to step when you do pointer arithmetic on it."},  # ~42
        {"role": "user", "content": "And what about references in C++?"},  # 6
        {"role": "assistant", "content": "A reference is an alias for an existing variable. Once bound, it cannot be made to refer to something else, and it cannot be null."},  # ~24
    ]
    # Case 2: firehose — teacher massively over-writes.
    firehose = [
        {"role": "user", "content": "Pointers?"},  # 1
        {"role": "assistant", "content": "A pointer is a variable. " * 60},  # ~240
    ]
    # Case 3: terse — teacher under-writes.
    terse = [
        {"role": "user", "content": "Tell me everything about how pointers work in C and why they're useful for systems programming."},  # 17
        {"role": "assistant", "content": "Memory addresses."},  # 2
    ]
    print("balanced ->", score(balanced, {}))
    print("firehose ->", score(firehose, {}))
    print("terse    ->", score(terse, {}))
