"""System and user prompts for the grader LLM.

Tone reference: `teachingbench/prompts.py::TRANSCRIPT_JUDGE_PROMPT` — short, role-clarifying,
expects JSON-only output, anchors are calibration points (not the only allowed values).

Grading scale is fixed 1-4 ordinal:
    1 = poor, 2 = needs improvement, 3 = satisfactory, 4 = excellent.
"""

from __future__ import annotations

DEFAULT_GRADER_SYSTEM_PROMPT = """\
You are an expert teacher grading a single piece of student work against a rubric.

Your job:
- Read the student work carefully.
- Apply the rubric criteria honestly — anchor on what the rubric says, not on whether the \
work feels impressive or earnest.
- Produce a single integer grade on the 1-4 scale:
    1 = poor
    2 = needs improvement
    3 = satisfactory
    4 = excellent
- Be calibrated, not sycophantic. A weak answer gets a 1 or 2 even if the student tried.
  A strong answer gets a 4 even if it is short. Do not inflate.
- Return ONLY the structured output: `{"grade": <1|2|3|4>, "rationale": "<one or two short \
sentences citing the rubric>"}`. No extra prose, no markdown fences.\
"""

GRADING_USER_PROMPT_TEMPLATE = """\
{prompt}

Rubric:
{rubric_text}

Student work:
<student_work>
{student_work}
</student_work>

Grade this work on the 1-4 scale. Return only the JSON object \
`{{"grade": <1|2|3|4>, "rationale": "<short>"}}`.\
"""


def format_rubric(rubric: list[dict]) -> str:
    """Render a rubric list as a numbered text block for the user prompt.

    Each criterion: `{"label": "<short name>", "anchors": [<str>, ...]}` (anchors optional).
    """
    if not rubric:
        return "(no rubric provided)"
    lines: list[str] = []
    for i, c in enumerate(rubric, 1):
        label = str(c.get("label") or c.get("id") or f"criterion_{i}")
        lines.append(f"{i}. **{label}**")
        anchors = c.get("anchors") or []
        for a in anchors:
            if isinstance(a, dict):
                score = a.get("score")
                meaning = str(a.get("meaning") or "").strip()
                if score is None:
                    lines.append(f"     - {meaning}")
                else:
                    lines.append(f"     - {score} → {meaning}")
            else:
                lines.append(f"     - {a}")
    return "\n".join(lines)
