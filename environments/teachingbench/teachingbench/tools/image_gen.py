"""Image-gen tool. Stub — returns a placeholder so plumbing can be exercised end-to-end.

Verifiers auto-derives the tool def from this function's signature/docstring via
`convert_func_to_tool_def`. A real generator drops in by replacing this function's body.
"""

from __future__ import annotations

from typing import Any


async def image_gen(prompt: str, style: str = "diagram") -> dict[str, Any]:
    """Generate a diagram or illustration. Use sparingly — only when prose alone is insufficient.

    Args:
        prompt: What to draw, in natural language.
        style: One of "diagram", "sketch", "photo".
    """
    return {
        "status": "stub",
        "url": None,
        "echo": {"prompt": prompt, "style": style},
        "note": "image_gen is stubbed in v0.1; plumbing only.",
    }
