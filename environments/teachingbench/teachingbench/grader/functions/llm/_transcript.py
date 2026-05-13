"""Render a message list into a Tutor:/Student: transcript string.

Mirrors `grader.judge._render_transcript` and `composers/v1_llm_only.py:_render_transcript`
exactly so per-criterion LLM judges see the same transcript shape the batched
v1 judge sees. Drops system messages, surfaces tool results, and flattens
multimodal content blocks to text.
"""

from __future__ import annotations


def render_transcript(messages: list[dict]) -> str:
    """Render a Tutor:/Student: transcript from a flat message list.

    - Drops `system` messages entirely.
    - `tool` role becomes a `[Tool result]: ...` line.
    - `assistant` → "Tutor:", everything else → "Student:".
    - Multimodal content (list of parts) is flattened to text by joining
      the `text` field of each part.
    """
    lines: list[str] = []
    for m in messages:
        role = m.get("role", "") if isinstance(m, dict) else getattr(m, "role", "")
        if role == "system":
            continue
        content = m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "")
        if isinstance(content, list):
            content = "\n".join(
                part.get("text", "") if isinstance(part, dict) else str(getattr(part, "text", ""))
                for part in content
            )
        content = str(content or "")
        if role == "tool":
            lines.append(f"[Tool result]: {content}")
            continue
        if not content:
            continue
        speaker = "Tutor" if role == "assistant" else "Student"
        lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


__all__ = ["render_transcript"]
