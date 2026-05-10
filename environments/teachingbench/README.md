# teachingbench

A Verifiers / Prime-Intellect RL environment that evaluates how well an LLM **teaches a specific concept** to a specific student.

Each rollout is a multi-turn dialog (1..N turns, set per task) between the tutor model under test and a simulated student. After the dialog ends, an LLM judge scores the full transcript against a structured per-criterion rubric. Reward = mean of non-null per-criterion scores.

## Status

v0.1 — runnable, two sample tasks (`cs/intro_python_hello_world`, `cs/recursion_base_cases`). Reward path is the LLM judge; quiz / self-rating code in `grader/quiz.py` and `LLMStudent.{answer_quiz,self_rate}` is dormant.

## Local development

```bash
# from the repo root
cd environments/teachingbench
pip install -e .

# dry-run (no API calls — verifies dataset + imports):
python -m teachingbench.smoke_test

# live (one rollout against real models):
python -m teachingbench.smoke_test --live \
    --task cs/intro_python_hello_world \
    --tutor-model gpt-5.4-nano \
    --student-model gpt-5.4-mini \
    --judge-model gpt-5.4-nano
```

Live runs save outputs to `environments/teachingbench/outputs/runs/<timestamp>__<task>__<model>/{results.jsonl, metadata.json}`.

## Push to Prime

From the repo root:

```bash
prime env push --path environments/teachingbench
```

`prime env push` builds the wheel locally then uploads. The metadata test runs on Prime's side — verify the Prime dashboard shows it passing; CLI exit-success is **not** sufficient.

### Pre-push wheel verification

```bash
pip wheel environments/teachingbench --no-deps -w /tmp/wheel_test
unzip -l /tmp/wheel_test/teachingbench-0.1.0-py3-none-any.whl   # confirm tasks/* shipped
pip install --force-reinstall --no-deps /tmp/wheel_test/teachingbench-0.1.0-py3-none-any.whl
cd /tmp && python -m teachingbench.smoke_test                    # no source-tree dep
```

## Package layout

```
teachingbench/
├── env.py              # TeachingEnv (MultiTurnEnv subclass) + load_environment
├── smoke_test.py       # one-rollout driver, dry-run + live modes
├── prompts.py          # DEFAULT_TUTOR_SYSTEM_PROMPT (empty), DEFAULT_STUDENT_SYSTEM_PROMPT,
│                       #   DEFAULT_RUBRIC, TRANSCRIPT_JUDGE_PROMPT
├── dataset.py          # discovers tasks from tasks/<subject>/<topic>/, builds HF Dataset
├── student/            # Student protocol + LLMStudent (active) + HumanStudent (stub)
├── grader/judge.py     # TeachingRubric (subclass of vf.JudgeRubric); transcript_score reward
├── grader/quiz.py      # dormant — quiz/self-rating reward path, kept for re-enable
├── tools/image_gen.py  # stub tool; verifiers auto-derives the schema from the function signature
└── tasks/              # one folder per topic; meta.yaml + optional materials/
```

## Key design constraints

- **Tutor system prompt defaults to empty** — realistic case is "user opens ChatGPT, no system prompt." Per-task `tutor_system_prompt` in meta.yaml replaces the default.
- **Student system prompt** = generic behavior rules (50-word cap, "you are not the tutor", typos OK, etc.) + per-task situational orientation appended.
- **Per-task `turns: N`** — `turns: 1` ⇒ no student LLM call (seed → tutor → done). Higher N ⇒ N student-tutor exchanges before the judge scores.
- **Programmable student messages** — task can pin specific student replies via `fixed_student_followups` (turns 2..N+1).
- **Rubric is structured** — list of `{id, description, anchors}` criteria. Default in `prompts.py`; per-task override possible.
- **Null criteria** — judge returns null when a criterion doesn't apply (e.g. `bridging` when no materials uploaded). Composite is mean of non-null criteria.
- **Tutor model is general** — Verifiers passes the rollout `client` and `model`; nothing pinned.
- **Tool calls supported** — `image_gen` stubbed but the dispatch path is live.
```

## Configuration via `load_environment`

```python
load_environment(
    judge_client=...,           # AsyncOpenAI, defaults to env-var-driven AsyncOpenAI()
    judge_model="gpt-5.4-nano",
    student_client=...,         # defaults to judge_client
    student_model=...,          # defaults to judge_model
    default_turns=4,            # fallback when meta.yaml has no `turns:`
    max_turns=32,               # hard ceiling
    pass_threshold=0.6,
    task_filter=None,           # restrict to a single task_id
)
```

## See also

- Repo-root `PLAN.md` — phase plan + open follow-ups.
- Repo-root `PROGRESS.md` — checkbox status per phase.
