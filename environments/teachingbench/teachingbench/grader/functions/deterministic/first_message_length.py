"""First-message length, prose only.

Measures: word count of the FIRST teacher message in the conversation,
with code blocks stripped first.

Good: an opening response that gives the student something to react to
without burying them — a paragraph or two, maybe a small worked example.
Bad: the model treats the first turn as "answer everything at once" and
dumps a multi-section essay before the student has had a chance to
specify what they actually want.

Thresholds:
- good_at = 200 words — generous; allows a short setup + answer + a
  follow-up nudge.
- zero_at = 700 words — multi-page opening. By this point the model is
  guaranteed firehosing.

Why a separate first-message criterion when we already have
`anti_firehose_length`? Because firehose behavior concentrates heavily in
turn 1 — many models give a long first answer and then shorten up as the
dialogue continues, and the *mean* can mask that. First-message length is
the strongest single signal of "model treated this like a one-shot
prompt". Code is stripped so a legitimate code demo doesn't penalize.
Returns None if no teacher turns.
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    linear_decay,
    strip_code_blocks,
    teacher_turns,
    word_count,
)


GOOD_AT = 200.0
ZERO_AT = 700.0


def score(messages: list[dict], task_info: dict) -> float | None:
    turns = teacher_turns(messages)
    if not turns:
        return None
    first_words = word_count(strip_code_blocks(turns[0]))
    return linear_decay(first_words, good_at=GOOD_AT, zero_at=ZERO_AT)


if __name__ == "__main__":
    concise = [
        {"role": "user", "content": "What's a pointer?"},
        {"role": "assistant", "content": "A pointer stores a memory address. " * 30},  # ~120 words
    ]
    firehose = [
        {"role": "user", "content": "What's a pointer?"},
        {"role": "assistant", "content": "A pointer stores a memory address. " * 200},  # ~800 words
    ]
    code_heavy = [
        {"role": "user", "content": "Show me."},
        {"role": "assistant", "content": "Brief prose.\n\n```c\n" + ("int x = 0;\n" * 500) + "```"},
    ]
    print("concise    ->", score(concise, {}))
    print("firehose   ->", score(firehose, {}))
    print("code_heavy ->", score(code_heavy, {}))
