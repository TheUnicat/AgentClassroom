# Tasks

One folder per topic. Each task folder holds the student's source materials and any topic-specific config. Quizzes are **generated post-teaching** by the grader, so they're not stored here.

## Expected layout (per task)

```
tasks/
└── <subject>/
    └── <topic_slug>/
        ├── meta.yaml          # subject, topic name, difficulty band, source attribution
        ├── materials/         # markdown files the student is "using in their course"
        │   ├── lecture_notes.md
        │   ├── textbook_excerpt.md
        │   └── problem_set.md
        └── seed_question.md   # the opening student question that kicks off the dialog
```

## Subjects (v0.1)

- `math/`
- `cs/`

## Authoring notes

- Markdown only for v0.1. PDF / image materials are v0.2.
- Materials should be realistic — drawn from actual course slides, textbook chapters, problem sets — not synthesized.
- Difficulty band per topic helps the grader calibrate quiz difficulty (avoid the easy-probe reward hack).
- Don't put quiz questions in the task folder. The grader generates them after the teaching turn so a tutor can't memorize and leak verbatim answers.
