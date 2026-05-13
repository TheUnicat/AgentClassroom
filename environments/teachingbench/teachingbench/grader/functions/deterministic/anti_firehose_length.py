"""Anti-firehose: mean teacher words per turn, prose only.

Measures: how verbose the teacher is on average across the conversation,
after stripping code blocks (we don't want to penalize a teacher for
showing a worked example).

Good: short, focused turns. A back-and-forth dialogue with ~paragraph-
sized teacher messages keeps the student in the driver's seat.
Bad: every turn is a lecture. The student asks a follow-up and the
teacher dumps another 600 words.

Thresholds:
- good_at = 150 words/turn — roughly one paragraph. A reasonable amount
  of explanation for a typical follow-up; not punishingly short.
- zero_at = 500 words/turn — about a full page of prose. At this rate
  the teacher is monologuing every turn; the student isn't being taught,
  they're being lectured.

Code is stripped before counting so worked examples don't accidentally
count as firehose. Inline code is also stripped (a teacher repeatedly
referencing `malloc` shouldn't inflate the count). If there are no
teacher turns at all, returns None (criterion N/A).
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    linear_decay,
    strip_code_blocks,
    teacher_turns,
    word_count,
)


GOOD_AT = 150.0
ZERO_AT = 500.0


def score(messages: list[dict], task_info: dict) -> float | None:
    turns = teacher_turns(messages)
    if not turns:
        return None
    total_words = sum(word_count(strip_code_blocks(t)) for t in turns)
    mean = total_words / len(turns)
    return linear_decay(mean, good_at=GOOD_AT, zero_at=ZERO_AT)


if __name__ == "__main__":
    short = [
        {"role": "user", "content": "Explain pointers."},
        {"role": "assistant", "content": "A pointer stores a memory address. " * 20},  # ~80 words
        {"role": "user", "content": "OK and references?"},
        {"role": "assistant", "content": "A reference is an alias. " * 15},  # ~60 words
    ]
    firehose = [
        {"role": "user", "content": "Explain pointers."},
        {"role": "assistant", "content": "A pointer stores a memory address. " * 200},  # ~800 words
    ]
    with_code = [
        {"role": "user", "content": "Show me."},
        {"role": "assistant", "content": "Short prose.\n\n```c\n" + ("int x = 0;\n" * 200) + "```"},
    ]
    print("short    ->", score(short, {}))
    print("firehose ->", score(firehose, {}))
    print("withcode ->", score(with_code, {}))
