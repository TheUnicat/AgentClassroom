"""Deterministic judge: question_density.

Measures the average number of questions the teacher asks the student per
teacher turn. Counts `?` characters in teacher prose (code blocks stripped,
so `?` inside `if x == None?` or shell prompts doesn't count).

Why it matters:
- 0 questions/turn = pure lecturing; no diagnostic engagement.
- ~1 question/turn = healthy dialogic teaching ("does that make sense so
  far?", "what do you think happens if..?"). Highest score.
- ≥4 questions/turn = Socratic interrogation, often unwanted when the
  student arrived asking for a direct answer.

Scoring: tent kernel centered at 1.0 with half-width 3.0
(via `_utils.tent`). Concretely:
    mean_q = 0   → 0.667 (lecturing, lukewarm)
    mean_q = 1   → 1.000 (peak)
    mean_q = 2   → 0.667
    mean_q = 3   → 0.333
    mean_q ≥ 4   → 0.000 (interrogation)

Returns None if there are no teacher turns.
"""

from __future__ import annotations

from teachingbench.grader.functions.deterministic._utils import (
    strip_code_blocks,
    teacher_turns,
    tent,
)


def score(messages: list[dict], task_info: dict) -> float | None:
    turns = teacher_turns(messages)
    if not turns:
        return None
    total_q = sum(strip_code_blocks(t).count("?") for t in turns)
    mean_q = total_q / len(turns)
    return tent(mean_q, peak=1.0, half_width=3.0)


def score_turn(messages: list[dict], task_info: dict) -> float | None:
    """Question count in the latest teacher turn's prose, scored via tent."""
    turns = teacher_turns(messages)
    if not turns:
        return None
    q = strip_code_blocks(turns[-1]).count("?")
    return tent(q, peak=1.0, half_width=3.0)


if __name__ == "__main__":
    lecturing = [
        {"role": "user", "content": "explain recursion"},
        {"role": "assistant", "content": "Recursion is when a function calls itself. Here is an example: def fact(n): return 1 if n==0 else n*fact(n-1). The base case stops the recursion."},
    ]
    dialogic = [
        {"role": "user", "content": "explain recursion"},
        {"role": "assistant", "content": "Sure! Have you seen a function call itself before? Think of it like a russian doll. What would you guess happens at the smallest doll?"},
        {"role": "user", "content": "it stops?"},
        {"role": "assistant", "content": "Right! That's called the base case. Can you tell me what would happen without one?"},
    ]
    interrogation = [
        {"role": "user", "content": "show me a for loop"},
        {"role": "assistant", "content": "Why? What is your goal? What loop construct do you already know? Have you tried it? Where did you get stuck? Can you share code?"},
    ]
    empty = [{"role": "user", "content": "hi"}]
    print("lecturing:    ", score(lecturing, {}))
    print("dialogic:     ", score(dialogic, {}))
    print("interrogation:", score(interrogation, {}))
    print("no_turns:     ", score(empty, {}))
