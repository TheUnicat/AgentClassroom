"""Multimodal helpers: turn materials_media references into OpenAI content blocks.

When a task references PDFs or images in `meta.yaml`, this module:
  - PDFs → one PNG per page via ghostscript (cached on disk in `_materials/.cache/`)
  - Images (PNG/JPG/JPEG/WEBP) → base64 data URL directly
  - Returns OpenAI `image_url` content blocks ready to splice into a user message

The tutor sees these blocks in turn 1's user message and can vision-read them.
Student LLM and judge stay text-only for v0.1 — the persona's system prompt
already carries the relevant facts.
"""

from __future__ import annotations

import base64
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def materials_media_to_content_blocks(
    materials_media: list[dict[str, Any]],
    *,
    pdf_dpi: int = 150,
) -> list[dict[str, Any]]:
    """Build OpenAI `image_url` content blocks from a list of materials_media refs.

    Each ref is `{path, type, description}`. PDFs are rasterized to one image per
    page; image files are passed through directly. Order is preserved.
    """
    blocks: list[dict[str, Any]] = []
    for media in materials_media:
        path = media.get("path")
        mtype = media.get("type")
        if not path:
            continue
        if mtype == "image":
            blocks.append(_image_path_to_block(path))
        elif mtype == "pdf":
            blocks.extend(_pdf_path_to_blocks(path, dpi=pdf_dpi))
        else:
            logger.warning("Skipping material of unsupported type %r at %s", mtype, path)
    return blocks


def attach_media_to_first_user_message(
    prompt: list[dict[str, Any]],
    materials_media: list[dict[str, Any]],
    *,
    pdf_dpi: int = 150,
) -> list[dict[str, Any]]:
    """Convert the first user message's content into a multipart array (text + media)."""
    if not materials_media:
        return prompt
    blocks = materials_media_to_content_blocks(materials_media, pdf_dpi=pdf_dpi)
    if not blocks:
        return prompt

    new_prompt: list[dict[str, Any]] = []
    attached = False
    for msg in prompt:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
        if not attached and role == "user":
            content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            text = content if isinstance(content, str) else _stringify_content(content)
            new_prompt.append({
                "role": "user",
                "content": [{"type": "text", "text": text}] + blocks,
            })
            attached = True
        else:
            new_prompt.append(msg)
    return new_prompt


# --- internals --------------------------------------------------------------


def _image_path_to_block(path: str) -> dict[str, Any]:
    p = Path(path)
    ext = p.suffix.lower().lstrip(".")
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, f"image/{ext}")
    data = p.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def _pdf_path_to_blocks(pdf_path: str, *, dpi: int = 150) -> list[dict[str, Any]]:
    """Rasterize a PDF to per-page PNG content blocks. Cached on disk."""
    pdf = Path(pdf_path)
    cache_dir = pdf.parent / ".cache" / f"{pdf.stem}_{dpi}dpi"

    # Generate if cache miss. ghostscript zero-pads pageno via %d.
    if not cache_dir.is_dir():
        cache_dir.mkdir(parents=True)
        try:
            subprocess.run(
                [
                    "gs",
                    "-sDEVICE=png16m",
                    f"-r{dpi}",
                    "-dNOPAUSE",
                    "-dBATCH",
                    "-dQUIET",
                    f"-sOutputFile={cache_dir}/page_%03d.png",
                    str(pdf),
                ],
                check=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            logger.error("ghostscript failed to rasterize %s: %s", pdf, e)
            cache_dir.rmdir()  # don't leave an empty cache dir behind
            return []

    page_files = sorted(cache_dir.glob("page_*.png"))
    blocks: list[dict[str, Any]] = []
    for pf in page_files:
        data = pf.read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })
    return blocks


def _stringify_content(content: Any) -> str:
    """Defensive fallback if first user message content is already a list/object."""
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "\n".join(parts)
    return str(content)
