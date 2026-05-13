"""Echo score: did the teacher actually read the student's last turn?

Measures: bigram overlap between each teacher turn (after the first)
and the immediately preceding student turn, after stopword removal.
Averaged across those pairs.

Good: teacher picks up vocabulary the student just used ("you mentioned
malloc — let's stay with that"). Signals the teacher noticed what the
student said.
Bad: teacher's next turn ignores the student's wording and pivots to a
canned explanation. Pure non-echo = talking past them.

Bigrams (not unigrams) because single-word overlap is too noisy — any
on-topic reply will share the topic noun. Bigrams require the teacher to
echo a phrase, not just a keyword.

Thresholds:
- raw_echo >= 0.40 -> 1.0. Echoing 40% of the student's distinctive
  bigrams is strong active listening; higher would actually be parroting.
- raw_echo <= 0.05 -> 0.0. Below 5% the teacher is essentially writing
  independently of what the student said.
- Linear in between.

Returns None when there are no teacher-after-student pairs (single-turn
rollout, opener-only, etc.).
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    clamp01,
    strip_code_blocks,
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

GOOD_AT = 0.40  # raw echo above this -> full credit
ZERO_AT = 0.05  # raw echo below this -> zero credit


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


def _content_bigrams(text: str) -> set[tuple[str, str]]:
    toks = [w for w in words(strip_code_blocks(text)) if w not in _STOPWORDS]
    return {(toks[i], toks[i + 1]) for i in range(len(toks) - 1)}


def score(messages: list[dict], task_info: dict) -> float | None:
    # Pair each non-first assistant turn with the most recent prior user
    # turn (skipping the env-injected `[Session ended: ...]` sentinel).
    pairs: list[tuple[str, str]] = []
    last_user: str | None = None
    seen_assistant = False
    for m in messages:
        r = _role(m)
        if r == "user":
            text = _content(m).strip()
            if not text or (text.startswith("[Session ended:") and text.endswith("]")):
                continue
            last_user = text
        elif r == "assistant":
            text = _content(m)
            if not text:
                continue
            if seen_assistant and last_user is not None:
                pairs.append((last_user, text))
            seen_assistant = True

    if not pairs:
        return None

    ratios: list[float] = []
    for student_text, teacher_text in pairs:
        sb = _content_bigrams(student_text)
        if not sb:
            ratios.append(0.0)
            continue
        tb = _content_bigrams(teacher_text)
        ratios.append(clamp01(len(sb & tb) / max(1, len(sb))))

    raw_echo = sum(ratios) / len(ratios)
    if raw_echo >= GOOD_AT:
        return 1.0
    if raw_echo <= ZERO_AT:
        return 0.0
    return (raw_echo - ZERO_AT) / (GOOD_AT - ZERO_AT)


if __name__ == "__main__":
    # Case 1: heavy echo — teacher repeats student bigrams verbatim.
    echo_heavy = [
        {"role": "user", "content": "How do pointers work in C?"},
        {"role": "assistant", "content": "Pointers in C hold memory addresses."},
        {"role": "user", "content": "What about pointer arithmetic with arrays?"},
        {"role": "assistant", "content": "Pointer arithmetic with arrays scales by element size."},
    ]
    # Case 2: no echo — teacher pivots to unrelated phrasing each turn.
    no_echo = [
        {"role": "user", "content": "How do pointers work in C?"},
        {"role": "assistant", "content": "Let's start with memory."},
        {"role": "user", "content": "What about pointer arithmetic with arrays?"},
        {"role": "assistant", "content": "Consider how compilers translate index notation."},
    ]
    # Case 3: only one assistant turn -> None (no after-first turn).
    single = [
        {"role": "user", "content": "Explain X."},
        {"role": "assistant", "content": "X is a thing."},
    ]
    print("echo_heavy ->", score(echo_heavy, {}))
    print("no_echo    ->", score(no_echo, {}))
    print("single     ->", score(single, {}))
