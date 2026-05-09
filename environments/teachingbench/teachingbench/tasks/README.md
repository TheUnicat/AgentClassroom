# Tasks

One folder per topic. Each task folder holds a single `meta.yaml` plus an optional `materials/` directory.

## Layout (per task)

```
tasks/
└── <subject>/
    └── <topic_slug>/
        ├── meta.yaml          # all per-task config + content
        └── materials/         # OPTIONAL: markdown files the student "has"
            ├── lecture_notes.md
            └── textbook_excerpt.md
```

## `meta.yaml` schema

```yaml
task_id: <subject>/<slug>
subject: <e.g. cs>
topic: <human-readable name>
difficulty: <free-form label>
turns: <int, 1..N>           # number of student-tutor exchanges before judging

# All four below are optional.
tutor_system_prompt: |       # default: empty (realistic ChatGPT-like usage)
  ...
student_system_prompt: |     # default: a generic student prompt that interpolates {materials} and {topic}
  ...
fixed_student_followups:     # pinned messages for turns 2..N+1
  - "<turn 2's student message>"
  - "<turn 3's student message>"

seed_question: |             # turn 1's student message (required)
  ...                        # if you have materials, paste them in here too — student is "pasting their slides into ChatGPT"

rubric: |                    # the criteria the LLM judge scores against (optional; falls back to a default)
  - **criterion_a**: ...
  - **criterion_b**: ...
```

For very long content (huge rubrics or seed questions), you can drop a `seed_question.md` or `rubric.md` file in the task folder as a fallback — the loader uses the meta.yaml field first.

## Subjects (v0.1)

- `math/`
- `cs/`

## Authoring notes

- **Default tutor system prompt is empty** — that's the realistic case (user opens ChatGPT, no system prompt). If your task needs the tutor to know about materials, **bake them into `seed_question`** ("Here are my slides: ...") rather than scaffolding via system prompt.
- The student system prompt is a different story — student is a simulated confederate actor, so it gets primed via the default template (or a per-task override).
- Markdown only for v0.1. PDF / image materials are v0.2.
- Don't put quiz questions in the task folder. The grader scores the transcript directly against the rubric; quiz/self-rating code in `grader/quiz.py` is dormant for v0.1.
