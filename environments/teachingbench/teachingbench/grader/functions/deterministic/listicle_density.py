"""Listicle density: bullet/list/header markers per word of teacher prose.

Measures: how heavily the teacher leans on bulleted lists, numbered
lists, headers, and bolded "labels" relative to the volume of prose
they're writing.

Good: prose that uses lists sparingly, when content is genuinely
enumerable (a few discrete steps, a short comparison). Mild structure
helps comprehension.
Bad: every concept rendered as a five-bullet list with bolded labels and
H3 headers, regardless of whether the content is actually a list. This
is a classic chat-tuned-model failure mode — the model substitutes
visual structure for thought, and the student gets a wall of bullets
they can't actually engage with conversationally.

Markers counted (each occurrence once):
- `- ` bullets at line start
- `* ` bullets at line start (not bold)
- `N.` numbered lists at line start
- `#` through `######` headers at line start
- `**short bold**` (≤30 chars) used as inline labels

Code is stripped first so embedded Markdown inside a code fence doesn't
count.

Thresholds:
- good_at density = 0.015 (≈1 marker per 67 words) — light structure.
- zero_at density = 0.10 (≈1 marker per 10 words) — basically a pure
  listicle dump where prose has been replaced with bullets.

Returns None if no teacher turns or zero prose words.
"""

from __future__ import annotations

import re

from teachingbench.grader.functions.deterministic._utils import (
    linear_decay,
    strip_code_blocks,
    teacher_turns,
    word_count,
)


_DASH_BULLET = re.compile(r"^\s*-\s+", re.MULTILINE)
_STAR_BULLET = re.compile(r"^\s*\*\s+", re.MULTILINE)
_NUM_LIST = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_HEADER = re.compile(r"^\s*#{1,6}\s+", re.MULTILINE)
_SHORT_BOLD = re.compile(r"\*\*[^*]{1,30}\*\*")


GOOD_AT = 0.015
ZERO_AT = 0.10


def _markers(text: str) -> int:
    return (
        len(_DASH_BULLET.findall(text))
        + len(_STAR_BULLET.findall(text))
        + len(_NUM_LIST.findall(text))
        + len(_HEADER.findall(text))
        + len(_SHORT_BOLD.findall(text))
    )


def score(messages: list[dict], task_info: dict) -> float | None:
    turns = teacher_turns(messages)
    if not turns:
        return None
    total_markers = 0
    total_words = 0
    for t in turns:
        prose = strip_code_blocks(t)
        total_markers += _markers(prose)
        total_words += word_count(prose)
    if total_words == 0:
        return None
    density = total_markers / total_words
    return linear_decay(density, good_at=GOOD_AT, zero_at=ZERO_AT)


if __name__ == "__main__":
    prose_only = [
        {"role": "user", "content": "Explain pointers."},
        {
            "role": "assistant",
            "content": (
                "A pointer is a variable that stores the memory address of "
                "another variable. You can dereference it with the star operator "
                "to access the value at that address. References behave similarly "
                "but cannot be reseated."
            ),
        },
    ]
    listicle = [
        {"role": "user", "content": "Explain pointers."},
        {
            "role": "assistant",
            "content": (
                "## Pointers\n"
                "**Definition:** address holder\n"
                "- stores address\n"
                "- dereferenced with *\n"
                "- can be null\n"
                "1. declare\n"
                "2. assign\n"
                "3. use\n"
                "### Compared to references\n"
                "- can be reseated\n"
                "- can be null\n"
            ),
        },
    ]
    mild = [
        {"role": "user", "content": "Steps?"},
        {
            "role": "assistant",
            "content": (
                "There are three things to keep in mind when learning pointers. "
                "First, a pointer is just an address. Second, you dereference it "
                "to get the value. Third, dangling pointers cause undefined "
                "behavior so always initialize. Here's a short summary:\n"
                "- declare with type*\n"
                "- assign with &\n"
                "- dereference with *\n"
            ),
        },
    ]
    print("prose_only ->", score(prose_only, {}))
    print("listicle   ->", score(listicle, {}))
    print("mild       ->", score(mild, {}))
