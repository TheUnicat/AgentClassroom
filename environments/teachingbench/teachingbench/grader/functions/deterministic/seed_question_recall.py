"""Seed-question recall: does the closing teacher message tie back to
what the student originally asked?

Measures: fraction of content tokens from the seed question (the
student's very first turn) that reappear in the final teacher message.
Stopwords plus very common pedagogical fillers ("want", "learn",
"teach", "explain", "help", "know", "understand", "tell") are removed
from the seed before the comparison.

Good: teacher's last word references the original goal — closes the
loop. The student walks away with their actual question answered.
Bad: teacher drifted onto tangents and the final turn is about
something else entirely (or is pure pleasantries).

Code blocks in the final teacher turn are stripped — we care about
prose-level recall, not whether a variable name happened to match a
seed token.

Thresholds:
- recall >= 0.50 -> 1.0. Half of the seed's content words appearing in
  the closing turn is solid evidence the teacher remembered the goal.
- recall <= 0.05 -> 0.0. Below 5% the final turn is effectively
  disconnected from the seed.
- Linear in between.

Returns None when:
- The seed has fewer than 3 distinct content tokens after filtering.
  ("teach me python" -> just {"python"} -> too thin to be meaningful.)
- There are no teacher turns in the transcript.
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    seed_question,
    strip_code_blocks,
    teacher_turns,
    words,
)


_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "i", "you", "to", "of",
    "in", "on", "and", "or", "but", "for", "with", "it", "this", "that",
    "be", "have", "has", "had", "do", "does", "did", "what", "how", "why",
    "when", "where", "so", "if", "not", "no", "yes", "ok", "okay", "as",
    "at", "by", "from", "my", "me", "we", "they", "them", "their", "your",
    "its",
})

_PEDAGOGICAL_FILLERS = frozenset({
    "want", "learn", "teach", "explain", "help", "know", "understand", "tell",
})

_FILTER = _STOPWORDS | _PEDAGOGICAL_FILLERS

GOOD_AT = 0.50
ZERO_AT = 0.05
MIN_SEED_TOKENS = 3


def _content_tokens(text: str) -> set[str]:
    return {w for w in words(text) if w not in _FILTER}


def score(messages: list[dict], task_info: dict) -> float | None:
    teachers = teacher_turns(messages)
    if not teachers:
        return None

    seed_tokens = _content_tokens(seed_question(messages))
    if len(seed_tokens) < MIN_SEED_TOKENS:
        return None

    final_tokens = _content_tokens(strip_code_blocks(teachers[-1]))
    recall = len(seed_tokens & final_tokens) / max(1, len(seed_tokens))

    if recall >= GOOD_AT:
        return 1.0
    if recall <= ZERO_AT:
        return 0.0
    return (recall - ZERO_AT) / (GOOD_AT - ZERO_AT)


if __name__ == "__main__":
    # Case 1: final turn echoes seed-question content tokens.
    grounded = [
        {"role": "user", "content": "I want to understand how pointers and references differ in C++."},
        {"role": "assistant", "content": "Sure. Let's start with the basics."},
        {"role": "user", "content": "OK."},
        {"role": "assistant", "content": "To wrap up: pointers can be reassigned and nulled; references are fixed aliases. That's the core difference in C++."},
    ]
    # Case 2: final turn drifted away.
    drifted = [
        {"role": "user", "content": "I want to understand how pointers and references differ in C++."},
        {"role": "assistant", "content": "Sure. Let's start."},
        {"role": "user", "content": "OK."},
        {"role": "assistant", "content": "Anyway, the most important thing is to practice writing small programs. Build a habit."},
    ]
    # Case 3: vague seed -> None.
    vague = [
        {"role": "user", "content": "teach me python"},
        {"role": "assistant", "content": "OK. Python is a programming language."},
    ]
    print("grounded ->", score(grounded, {}))
    print("drifted  ->", score(drifted, {}))
    print("vague    ->", score(vague, {}))
