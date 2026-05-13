"""Pure-Python helpers for deterministic judge functions.

Stdlib only. No teachingbench-specific imports, no `openai`, no `anthropic`,
no `verifiers`. This keeps the whole `deterministic/` subtree liftable
into a standalone judging-only repo.

Functions here are intentionally minimal; per-function modules may add
their own inline regex / counting helpers when behavior is local.
"""

from __future__ import annotations

import re
from typing import Any


# --- message extraction ----------------------------------------------------


def _content(msg: Any) -> str:
    """Extract a single string from a message's `content`, which may be a
    string or a list of parts (multimodal). Non-text parts are dropped."""
    if isinstance(msg, dict):
        c = msg.get("content", "")
    else:
        c = getattr(msg, "content", "")
    if isinstance(c, list):
        parts: list[str] = []
        for p in c:
            if isinstance(p, dict):
                t = p.get("text") or p.get("content")
            else:
                t = getattr(p, "text", None)
            if t:
                parts.append(str(t))
        return "\n".join(parts)
    return str(c or "")


def _role(msg: Any) -> str:
    if isinstance(msg, dict):
        return str(msg.get("role", ""))
    return str(getattr(msg, "role", ""))


def teacher_turns(messages: list[dict]) -> list[str]:
    """Ordered list of non-empty assistant (teacher) message texts.
    Excludes system and tool messages."""
    return [_content(m) for m in messages if _role(m) == "assistant" and _content(m)]


def student_turns(messages: list[dict]) -> list[str]:
    """Ordered list of student (user) message texts.

    Excludes system messages and excludes the session-ended sentinel
    that appears as a user message like `[Session ended: ...]` — those
    are env-injected, not real student turns.
    """
    out: list[str] = []
    for m in messages:
        if _role(m) != "user":
            continue
        t = _content(m).strip()
        if not t:
            continue
        if t.startswith("[Session ended:") and t.endswith("]"):
            continue
        out.append(t)
    return out


def seed_question(messages: list[dict]) -> str:
    """The student's first non-empty user turn — the original seed."""
    s = student_turns(messages)
    return s[0] if s else ""


# --- tokenization ----------------------------------------------------------


_WORD_RE = re.compile(r"\b[\w']+\b", re.UNICODE)


def words(text: str) -> list[str]:
    """Lowercased word tokens, ignoring punctuation."""
    return [w.lower() for w in _WORD_RE.findall(text)]


def word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


# --- code-fence helpers ----------------------------------------------------


_FENCE_RE = re.compile(r"```(\w+)?\n?([\s\S]*?)```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def strip_code_blocks(text: str) -> str:
    """Remove fenced and inline code so prose-oriented measures aren't
    dominated by code volume."""
    text = _FENCE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    return text


def code_blocks(text: str) -> list[tuple[str, str]]:
    """Return [(language, body), ...] for each fenced code block.
    `language` may be empty string if the fence had no language tag."""
    return [(m.group(1) or "", m.group(2) or "") for m in _FENCE_RE.finditer(text)]


# --- LaTeX helpers ---------------------------------------------------------
#
# Detection covers the LaTeX forms that actually show up in our rollouts:
#   display:  \[ ... \]   $$ ... $$   \begin{equation}/{align}/{gather}/...
#   inline:   \( ... \)
# Single-$ delimiters are NOT matched — too ambiguous with prose dollar
# signs ("the API costs $5"), and our rollouts use \( / \[ consistently.

_LATEX_DISPLAY_RE = re.compile(
    r"\\\[[\s\S]*?\\\]"
    r"|\$\$[\s\S]*?\$\$"
    r"|\\begin\{(?:equation|align|gather|displaymath|eqnarray|multline)\*?\}"
    r"[\s\S]*?"
    r"\\end\{(?:equation|align|gather|displaymath|eqnarray|multline)\*?\}",
    re.MULTILINE,
)
_LATEX_INLINE_RE = re.compile(r"\\\([\s\S]*?\\\)", re.MULTILINE)


def latex_display_blocks(text: str) -> list[str]:
    """Return the raw substring of each display-style equation block.
    Useful for treating each block as a structural marker."""
    return _LATEX_DISPLAY_RE.findall(text)


def strip_latex(text: str) -> str:
    """Strip display + inline LaTeX so prose-oriented measures (Flesch-
    Kincaid, type/token ratio, concept_velocity) aren't fooled by
    short symbol tokens (`x`, `n`, `frac`, `lim`) bringing the apparent
    readability down. Replaces matched LaTeX with a single space."""
    text = _LATEX_DISPLAY_RE.sub(" ", text)
    text = _LATEX_INLINE_RE.sub(" ", text)
    return text


def latex_density(text: str) -> float:
    """Fraction of `text` characters inside LaTeX expressions, in [0, 1].
    Counts both display and inline forms."""
    if not text:
        return 0.0
    latex_chars = 0
    for m in _LATEX_DISPLAY_RE.finditer(text):
        latex_chars += m.end() - m.start()
    for m in _LATEX_INLINE_RE.finditer(text):
        latex_chars += m.end() - m.start()
    return min(1.0, latex_chars / len(text))


# --- saturation / clamps ---------------------------------------------------


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def linear_decay(value: float, *, good_at: float, zero_at: float) -> float:
    """Map `value` to [0, 1] via piecewise-linear decay.

    Returns 1.0 if `value <= good_at`, 0.0 if `value >= zero_at`, and a
    linear interpolation in between. `zero_at` must be > `good_at`.
    """
    if zero_at <= good_at:
        return 1.0 if value <= good_at else 0.0
    if value <= good_at:
        return 1.0
    if value >= zero_at:
        return 0.0
    return 1.0 - (value - good_at) / (zero_at - good_at)


def tent(value: float, *, peak: float, half_width: float) -> float:
    """Triangular kernel centered at `peak`, dropping linearly to 0 at
    `peak ± half_width`. Useful for "good is in a range, both too low and
    too high are bad" scoring."""
    if half_width <= 0:
        return 1.0 if value == peak else 0.0
    return clamp01(1.0 - abs(value - peak) / half_width)
