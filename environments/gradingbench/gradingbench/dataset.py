"""Load grading examples from `data/synthetic.jsonl` into a HuggingFace Dataset row per task.

Each row in the JSONL file has the schema:

    {
        "task_id": "essay-001",
        "subject": "english" | "math" | "cs" | "history" | ...,
        "prompt": "Grade the following student response to this question: ...",
        "student_work": "<the actual student answer>",
        "rubric": [
            {"label": "thesis clarity", "anchors": [...]},
            ...
        ],
        "ground_truth_grade": 3,                 # int in [1,4]
        "ground_truth_rationale": "<optional>",
        "grader_id": "teacher_a"
    }

TODO: replace `data/synthetic.jsonl` with real human-graded data. The current file is
5 hand-crafted placeholder rows spanning subjects (english x2, math, cs, history) and
the 1-4 grade range.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from datasets import Dataset

from gradingbench.prompts import GRADING_USER_PROMPT_TEMPLATE, format_rubric

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_DATASET_PATH = DATA_DIR / "synthetic.jsonl"

VALID_GRADES = (1, 2, 3, 4)


def _validate_row(row: dict[str, Any], where: str) -> dict[str, Any]:
    """Validate one row and return a normalized copy. Raises ValueError on bad schema."""
    if not isinstance(row, dict):
        raise ValueError(f"{where}: row must be a dict, got {type(row).__name__}")

    task_id = row.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError(f"{where}: missing or empty 'task_id'")

    subject = str(row.get("subject") or "unknown").strip()

    prompt = row.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"{where}: task_id={task_id!r}: missing or empty 'prompt'")

    student_work = row.get("student_work")
    if not isinstance(student_work, str) or not student_work.strip():
        raise ValueError(f"{where}: task_id={task_id!r}: missing or empty 'student_work'")

    rubric = row.get("rubric") or []
    if not isinstance(rubric, list):
        raise ValueError(f"{where}: task_id={task_id!r}: 'rubric' must be a list")
    for i, c in enumerate(rubric):
        if not isinstance(c, dict):
            raise ValueError(f"{where}: task_id={task_id!r}: rubric[{i}] must be a mapping")
        if not (c.get("label") or c.get("id")):
            raise ValueError(f"{where}: task_id={task_id!r}: rubric[{i}] needs 'label' or 'id'")

    gt = row.get("ground_truth_grade")
    try:
        gt_int = int(gt)
    except (TypeError, ValueError):
        raise ValueError(
            f"{where}: task_id={task_id!r}: 'ground_truth_grade' must be int in {VALID_GRADES}, got {gt!r}"
        )
    if gt_int not in VALID_GRADES:
        raise ValueError(
            f"{where}: task_id={task_id!r}: 'ground_truth_grade' must be in {VALID_GRADES}, got {gt_int}"
        )

    gt_rationale = row.get("ground_truth_rationale") or ""
    if not isinstance(gt_rationale, str):
        raise ValueError(f"{where}: task_id={task_id!r}: 'ground_truth_rationale' must be a string")

    grader_id = str(row.get("grader_id") or "unknown").strip()

    return {
        "task_id": task_id.strip(),
        "subject": subject,
        "prompt": prompt.strip(),
        "student_work": student_work,
        "rubric": rubric,
        "ground_truth_grade": gt_int,
        "ground_truth_rationale": gt_rationale,
        "grader_id": grader_id,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open() as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{lineno}: bad JSON: {e}") from e
    return rows


def load_rows(path: Path | None = None) -> list[dict[str, Any]]:
    """Read + validate raw rows from the JSONL file (no HF Dataset wrapping)."""
    path = path or DEFAULT_DATASET_PATH
    if not path.is_file():
        raise FileNotFoundError(f"gradingbench dataset not found at {path}")
    raw = _read_jsonl(path)
    if not raw:
        raise ValueError(f"gradingbench dataset at {path} is empty")
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, row in enumerate(raw):
        normalized = _validate_row(row, where=f"{path}:row{i+1}")
        if normalized["task_id"] in seen_ids:
            raise ValueError(f"{path}: duplicate task_id {normalized['task_id']!r}")
        seen_ids.add(normalized["task_id"])
        out.append(normalized)
    return out


def load_dataset(num_examples: int | None = None, path: Path | None = None) -> Dataset:
    """Build a HF Dataset from the JSONL file. Each row exposes:

    - `question`: the rendered grader user prompt (rubric + student work + instructions)
    - `answer`: empty string (single-turn; reward comes from `info.ground_truth_grade`)
    - `info`: JSON string carrying task_id, subject, rubric, ground_truth_grade, etc.
    """
    rows = load_rows(path)
    if num_examples is not None:
        rows = rows[: int(num_examples)]

    out_rows: list[dict[str, Any]] = []
    for r in rows:
        question = GRADING_USER_PROMPT_TEMPLATE.format(
            prompt=r["prompt"],
            rubric_text=format_rubric(r["rubric"]),
            student_work=r["student_work"],
        )
        out_rows.append(
            {
                "question": question,
                "answer": "",
                "info": json.dumps(
                    {
                        "task_id": r["task_id"],
                        "subject": r["subject"],
                        "prompt": r["prompt"],
                        "rubric": r["rubric"],
                        "ground_truth_grade": r["ground_truth_grade"],
                        "ground_truth_rationale": r["ground_truth_rationale"],
                        "grader_id": r["grader_id"],
                    }
                ),
            }
        )
    return Dataset.from_list(out_rows)
