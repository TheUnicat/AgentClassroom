# teachingbench

Verifiers env. The tutor model teaches a concept off of the student's own course materials; the student (LLM or human) takes an LLM-generated quiz on what was just taught and self-rates how much they learned. Reward = quiz score + self-rating.

## Status

**Skeleton.** Verifiers integration, task content, grader, and student implementations are stubs. See `PROGRESS.md` at the repo root for the build sequence.

## Local development

```bash
# from the repo root
cd environments/teachingbench
pip install -e .
python -m teachingbench.smoke_test    # placeholder until env.py is wired up
```

## Push to Prime

From the repo root:

```bash
prime env push --path environments/teachingbench
```

`prime env push` builds the wheel locally then uploads. The metadata test runs on Prime's side — verify the Prime dashboard shows it passing; CLI exit-success is **not** sufficient.

### Pre-push wheel verification

```bash
pip wheel environments/teachingbench --no-deps -w /tmp/wheel_test
unzip -l /tmp/wheel_test/teachingbench-0.1.0-py3-none-any.whl
pip install --force-reinstall /tmp/wheel_test/teachingbench-0.1.0-py3-none-any.whl
cd /tmp && python -m teachingbench.smoke_test
```

If the smoke test runs cleanly from `/tmp`, the wheel has no source-tree dependency.

## Package layout

```
teachingbench/
├── env.py              # MultiTurnEnv subclass + load_environment factory
├── smoke_test.py       # one-rollout driver
├── student/            # Student protocol + LLM and human implementations
│   ├── base.py
│   ├── llm.py
│   └── human.py
├── grader/             # quiz generation, quiz grading, self-rating, judge (v0.2)
│   ├── quiz.py
│   └── judge.py
├── tools/              # Chat Completions tool schemas + image-gen stub
│   ├── schemas.py
│   └── image_gen.py
└── tasks/              # student materials, one folder per topic
```

## Key design constraints

- **Multi-turn:** student can ask follow-ups before being quizzed.
- **Student is swappable.** LLM and human-in-the-loop both satisfy the `Student` protocol in `student/base.py`.
- **Model entry point is general.** Use the `AsyncOpenAI` client Verifiers passes into `rollout`. Don't pin model names.
- **Tool-calling supported, image-gen stubbed.** `tools/image_gen.py` returns a placeholder; plumbing exists so a real generator drops in later.
- **Reward shape:** quiz score + self-rating. Judge LLM is deferred to v0.2.
