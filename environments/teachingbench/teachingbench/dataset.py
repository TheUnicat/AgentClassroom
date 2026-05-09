"""Load tasks from `tasks/<subject>/<topic>/` into a HuggingFace Dataset row per task.

Per-task fields supported in `meta.yaml`:
- `task_id`, `subject`, `topic`, `difficulty` (metadata)
- `turns: int` (1..N) — number of student-tutor exchanges before the judge scores
- `tutor_system_prompt: str` (optional) — overrides the default tutor prompt; may
  contain `{materials}` and `{topic}` placeholders
- `student_system_prompt: str` (optional) — overrides the default student prompt
- `fixed_student_messages: list[str]` (optional) — pinned student messages for
  turns 2..N+1 (turn 1 is always `seed_question.md`). Shorter list ⇒ extra turns
  fall through to the student LLM.

Files in the task dir:
- `seed_question.md` (required) — turn 1's student message
- `materials/*.md` (optional) — concatenated into a single materials blob
- `rubric.md` (optional) — the judging rubric; falls back to a default
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from datasets import Dataset

from teachingbench.prompts import (
    DEFAULT_RUBRIC,
    DEFAULT_STUDENT_SYSTEM_PROMPT,
    DEFAULT_TUTOR_SYSTEM_PROMPT,
)

TASKS_ROOT = Path(__file__).parent / "tasks"


def discover_tasks(root: Path | None = None) -> list[Path]:
    root = root or TASKS_ROOT
    return sorted(p.parent for p in root.glob("*/*/meta.yaml"))


def load_task(task_dir: Path) -> dict[str, Any]:
    meta = yaml.safe_load((task_dir / "meta.yaml").read_text()) or {}
    seed_question = (task_dir / "seed_question.md").read_text().strip()

    materials_dir = task_dir / "materials"
    materials_chunks: list[str] = []
    if materials_dir.is_dir():
        for path in sorted(materials_dir.glob("*.md")):
            materials_chunks.append(f"## {path.stem}\n\n{path.read_text().strip()}")
    materials = "\n\n---\n\n".join(materials_chunks)

    rubric_path = task_dir / "rubric.md"
    rubric = rubric_path.read_text().strip() if rubric_path.is_file() else DEFAULT_RUBRIC

    topic = meta.get("topic", task_dir.name)

    tutor_prompt = render_prompt(
        meta.get("tutor_system_prompt") or DEFAULT_TUTOR_SYSTEM_PROMPT,
        materials=materials,
        topic=topic,
    )
    student_prompt = render_prompt(
        meta.get("student_system_prompt") or DEFAULT_STUDENT_SYSTEM_PROMPT,
        materials=materials,
        topic=topic,
    )

    fixed_followups = meta.get("fixed_student_messages") or []
    if not isinstance(fixed_followups, list):
        raise ValueError(f"{task_dir}/meta.yaml: fixed_student_messages must be a list")

    return {
        "task_id": meta.get("task_id") or f"{task_dir.parent.name}/{task_dir.name}",
        "subject": meta.get("subject", task_dir.parent.name),
        "topic": topic,
        "difficulty": meta.get("difficulty", "unknown"),
        "turns": int(meta.get("turns", 4)),
        "seed_question": seed_question,
        "materials": materials,
        "rubric": rubric,
        "tutor_system_prompt": tutor_prompt,
        "student_system_prompt": student_prompt,
        "fixed_student_followups": [str(m) for m in fixed_followups],
    }


def render_prompt(template: str, *, materials: str, topic: str) -> str:
    """Interpolate {materials} and {topic} if present; leave other braces alone."""
    out = template
    if "{materials}" in out:
        out = out.replace("{materials}", materials)
    if "{topic}" in out:
        out = out.replace("{topic}", topic)
    return out


def build_dataset(task_filter: str | None = None, root: Path | None = None) -> Dataset:
    """Build a HF Dataset with one row per task. `info` is a JSON string (flat schema)."""
    rows: list[dict[str, Any]] = []
    for task_dir in discover_tasks(root):
        loaded = load_task(task_dir)
        if task_filter and loaded["task_id"] != task_filter:
            continue
        rows.append(
            {
                "question": loaded["seed_question"],
                "answer": "",
                "info": json.dumps(
                    {
                        "task_id": loaded["task_id"],
                        "subject": loaded["subject"],
                        "topic": loaded["topic"],
                        "difficulty": loaded["difficulty"],
                        "turns": loaded["turns"],
                        "materials": loaded["materials"],
                        "rubric": loaded["rubric"],
                        "tutor_system_prompt": loaded["tutor_system_prompt"],
                        "student_system_prompt": loaded["student_system_prompt"],
                        "fixed_student_followups": loaded["fixed_student_followups"],
                    }
                ),
            }
        )
    if not rows:
        raise ValueError(
            f"No tasks found under {root or TASKS_ROOT}"
            + (f" matching filter {task_filter!r}" if task_filter else "")
        )
    return Dataset.from_list(rows)
