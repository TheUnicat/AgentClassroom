### (Demo at https://agentclassroom.pages.dev)
# TeachingBench

A Verifiers / Prime-Intellect RL environment that evaluates how well an LLM **teaches a specific concept** to a specific student, grounded in materials the student is actually using (slides, textbook excerpts, problem sets).

The framing differentiator vs other teaching benchmarks: the model has to teach **off of the student's existing materials**, not give a generic explainer.

## Layout

```
.
├── .prime/                      # Prime Intellect lab config
├── environments/
│   └── teachingbench/           # the env package (push this to Prime)
│       ├── pyproject.toml
│       ├── README.md
│       └── teachingbench/
│           ├── env.py           # MultiTurnEnv subclass
│           ├── smoke_test.py
│           ├── student/         # LLM and human-in-the-loop students
│           ├── grader/          # quiz generation + scoring + self-rating
│           ├── tools/           # tool-call plumbing (incl. image-gen stub)
│           └── tasks/           # student materials per topic
├── PLAN.md
├── PROGRESS.md
└── TEACHING_ENV_KICKOFF.md
```

## Quick links

- Plan: [`PLAN.md`](PLAN.md)
- Progress checklist: [`PROGRESS.md`](PROGRESS.md)
- Original kickoff: [`TEACHING_ENV_KICKOFF.md`](TEACHING_ENV_KICKOFF.md)
- Env-level README: [`environments/teachingbench/README.md`](environments/teachingbench/README.md)
