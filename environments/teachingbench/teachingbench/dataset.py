"""Load tasks from `tasks/<subject>/<topic>/` into a HuggingFace Dataset row per task."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from datasets import Dataset

TASKS_ROOT = Path(__file__).parent / "tasks"


def discover_tasks(root: Path | None = None) -> list[Path]:
    root = root or TASKS_ROOT
    paths: list[Path] = []
    for meta_path in root.glob("*/*/meta.yaml"):
        paths.append(meta_path.parent)
    return sorted(paths)


def load_task(task_dir: Path) -> dict[str, Any]:
    meta = yaml.safe_load((task_dir / "meta.yaml").read_text())
    seed_question = (task_dir / "seed_question.md").read_text().strip()
    materials_dir = task_dir / "materials"
    materials_chunks: list[str] = []
    if materials_dir.is_dir():
        for path in sorted(materials_dir.glob("*.md")):
            materials_chunks.append(f"## {path.stem}\n\n{path.read_text().strip()}")
    materials = "\n\n---\n\n".join(materials_chunks)
    return {
        "task_id": meta.get("task_id") or f"{task_dir.parent.name}/{task_dir.name}",
        "subject": meta.get("subject", task_dir.parent.name),
        "topic": meta.get("topic", task_dir.name),
        "difficulty": meta.get("difficulty", "unknown"),
        "seed_question": seed_question,
        "materials": materials,
    }


def build_dataset(task_filter: str | None = None, root: Path | None = None) -> Dataset:
    """Build a HF Dataset with one row per task. Each row's `info` is a JSON-serialized dict
    so the schema stays flat (kickoff §5: HF rejects mixed-shape dicts under one column).
    """
    rows: list[dict[str, Any]] = []
    for task_dir in discover_tasks(root):
        loaded = load_task(task_dir)
        if task_filter and loaded["task_id"] != task_filter:
            continue
        rows.append(
            {
                "question": loaded["seed_question"],
                "answer": "",  # not used; reward is computed from state, not answer-matching
                "task": loaded["task_id"],
                "info": json.dumps(
                    {
                        "task_id": loaded["task_id"],
                        "subject": loaded["subject"],
                        "topic": loaded["topic"],
                        "difficulty": loaded["difficulty"],
                        "materials": loaded["materials"],
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
