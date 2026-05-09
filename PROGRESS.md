# PROGRESS: LLM Teaching-Quality RL Environment

Step-by-step checklist for the plan in `PLAN.md`. Mark `[x]` when done. Founder's 5 deliverables (D1–D5) tracked at the top.

---

## Founder's 5 deliverables (high-level status)

- [ ] **D1 — One-page pitch** (Phase 5)
- [ ] **D2 — Runnable repo** (Phases 1–3) — _skeleton landed, Verifiers wiring + Prime push pending_
- [ ] **D3 — Baseline report** — ≥3 models, 30–100 rollouts, failure taxonomy, 2–3 traces (Phase 4)
- [ ] **D4 — Data/rubric card** (Phase 5)
- [ ] **D5 — Demo artifact** — dashboard or Loom or both (Phase 5)

---

## Phase 0 — Decisions ✓

- [x] Subjects: Math + CS
- [x] Multi-turn (revised from kickoff default of single-turn)
- [x] Source materials: markdown only for v0.1
- [x] Modality: text + tool-calling (image-gen stubbed)
- [x] Student: LLM **and** human-in-the-loop both supported
- [x] Reward shape: LLM-generated quiz + student self-rating
- [x] Model entry point: general per Prime; no model pinning
- [x] Topic count target: 10–20
- [x] Public/held-out split: all public for v0.1
- [x] Sibling project access: confirmed unavailable; derive patterns from kickoff doc only

---

## Phase 1 — Skeleton ✓

### Top-level
- [x] `README.md`
- [x] `.gitignore`
- [x] `.prime/lab.json`

### Env package config
- [x] `environments/teachingbench/pyproject.toml` — hatchling build, `tags` field, deps for verifiers/openai/datasets, optional `materials` extras
- [x] `environments/teachingbench/README.md`

### Package skeleton
- [x] `teachingbench/__init__.py` — exposes `load_environment`
- [x] `teachingbench/env.py` — `TeachingEnv` class shell + `load_environment` factory
- [x] `teachingbench/smoke_test.py` — argparse + asyncio shell

### Student
- [x] `student/base.py` — `Student` Protocol (ask / answer_quiz / self_rate)
- [x] `student/llm.py` — `LLMStudent` stub
- [x] `student/human.py` — `HumanStudent` stub

### Grader
- [x] `grader/quiz.py` — `generate_quiz`, `score_quiz` stubs
- [x] `grader/judge.py` — judge LLM stub (deferred to v0.2)

### Tools
- [x] `tools/schemas.py` — Chat Completions tool registry + dispatch
- [x] `tools/image_gen.py` — stubbed image-gen tool with full Chat Completions schema

### Tasks
- [x] `tasks/README.md` — authoring layout

---

## Phase 2 — Wire up Verifiers + the reward pipeline

> Decision: LLMStudent first; HumanStudent stays a stub. Grading uses `vf.JudgeRubric` (PI's canonical LLM-judge format). Verifiers v0.1.14 — tool defs are now provider-agnostic (auto-derived from Python function signatures via `convert_func_to_tool_def`); the kickoff's "Chat Completions nested" note is stale.

### Env subclass
- [x] `TeachingEnv` subclasses `verifiers.MultiTurnEnv`
- [x] `setup_state(state)` loads materials, topic, turn-count state and injects per-task system prompt
- [x] `env_response(messages, state)` drives the dialog: tool-dispatch → student.decide → finalize (quiz + self-rate + score)
- [x] Termination via `state["final_env_response"]` (the `@vf.stop has_final_env_response` predicate); no message-content heuristics
- [x] `rollout(...)` not overridden (it's `@final` in MultiTurnEnv anyway)
- [x] Turn cap enforced (`max_student_turns`, default 8) plus a `max_turns` hard ceiling

### Internal model calls
- [x] LLMStudent, generate_quiz, score_quiz all take an `AsyncOpenAI` client + model — env wires `rubric.judge_client`/`judge_model` (or override) into both
- [x] No tutor model names hardcoded; tutor model flows from Verifiers' `client`/`model` rollout args. Env-side LLM defaults to `gpt-4.1-nano` (overridable via `load_environment`)

### Student
- [x] `LLMStudent.decide` implemented (returns `{"action": "follow_up"|"ready", "question": ...}`; JSON-parsed with fallback)
- [x] `LLMStudent.answer_quiz` implemented (per-item JSON, MCQ + free-response)
- [x] `LLMStudent.self_rate` implemented (1–5 Likert × clarity/coverage/confidence + free-text "still confusing")
- [ ] `HumanStudent.*` — **deferred** (LLM-first per kickoff alignment)

### Grader
- [x] `generate_quiz` produces 3 MCQ + 1 free-response, conditioned on teaching trace + materials
- [x] `score_quiz` computes per-item correctness (MCQ exact-match; free-response judged by LLM via JudgeRubric pattern) and combines with self-rating
- [x] Reward weighting: equal-weight composite = (quiz_score + self_rating_score) / 2 (open item to revisit after Phase 4)
- [x] `TeachingRubric(vf.JudgeRubric)` exposes `composite` as headline reward (weight 1.0) + zero-weight metrics: `quiz_score`, `self_rating_score`, `num_quiz_items`

### Tools
- [x] `image_gen` stub authored as a function; tool def auto-derived via `convert_func_to_tool_def`
- [x] Tool dispatch wired into `env_response` — checks `messages[-1].tool_calls`, dispatches via `_tool_map`, returns `ToolMessage`s

### Dataset
- [x] `dataset.py` — discovers tasks from `tasks/<subject>/<topic>/`, loads `meta.yaml` + `seed_question.md` + `materials/*.md`
- [x] `info` column serialized as JSON string (flat schema; HF won't reject mixed shapes)
- [x] One sample task authored: `cs/recursion_base_cases/` (intentionally a bit thin, to stress the "bridge to materials" failure mode)

### Smoke test
- [x] Argparse: `--task`, `--tutor-model`, `--judge-model`, `--base-url`, `--api-key-env`, `--max-student-turns`, `--live`
- [x] `--dry-run` (default) builds the dataset + imports env + lists tools, no API calls — fastest way to validate setup
- [x] `--live` runs a full rollout via `env.evaluate` (or `env.generate` fallback) and prints the score breakdown
- [ ] **Acceptance:** end-to-end rollout printed score breakdown — _pending_ (requires `pip install -e .` + API key; user should run)

---

## Phase 3 — Push v0.1.0 to Prime Intellect (D2 complete)

### Local wheel verification
- [ ] `pip wheel environments/teachingbench --no-deps -w /tmp/wheel_test` succeeds
- [ ] `unzip -l /tmp/wheel_test/teachingbench-0.1.0-py3-none-any.whl` shows tasks/ data files included
- [ ] `pip install --force-reinstall /tmp/wheel_test/...whl` succeeds
- [ ] `cd /tmp && python -m teachingbench.smoke_test` runs (no source-tree dependency)

### Push
- [ ] `prime env push --path environments/teachingbench` exits clean
- [ ] **Metadata test confirmed passing on Prime dashboard** (CLI exit-success NOT sufficient)
- [ ] v0.1.0 visible on Prime with one runnable task
- [ ] `prime eval run` skipped (needs billing; smoke test covers local dev)

---

## Phase 4 — Author tasks + baselines (D3)

### Authoring
- [ ] 10–20 tasks across math + CS subjects
- [ ] Each task: materials/, opening question, meta.yaml with difficulty band
- [ ] Difficulty calibrated per topic (close off easy-quiz hack)

### Baseline run
- [ ] ≥3 capability-stratified tutor models picked
- [ ] Capability-stratification check: small/cheap model not used as both tutor-under-test AND grader/student
- [ ] Student model family different from any tutor under test (prior-sharing check)
- [ ] 30–100 rollouts total executed
- [ ] Per-rollout artifacts saved: trace, tool calls, generated quiz, answers, self-rating, reward

### Analysis
- [ ] pass@1 / pass@k or mean reward computed per model
- [ ] Failure taxonomy drafted from traces
- [ ] 2–3 example traces selected (obvious failure, near-miss, clean win)
- [ ] **D3 baseline report written**

---

## Phase 5 — Pitch, rubric card, demo

### D1 — One-page pitch
- [ ] Opens with failure-frontier line
- [ ] One concrete failure mode per claim with a trace as evidence
- [ ] Commercial pull section (AI tutoring vertical, labs need teaching reward models, EdTech buyer path)
- [ ] **D1 done**

### D4 — Data/rubric card
- [ ] What the reward measures (quiz score + self-rating; weighting)
- [ ] Public vs held-out documented (v0.1: all public; quizzes generated post-hoc)
- [ ] Reward-hack surfaces enumerated:
  - [ ] Tutor leaks quiz answers during teaching → quiz is post-teaching, but flag verbatim overlap with materials
  - [ ] Self-rating gaming → check correlation with quiz score; flag large gaps
  - [ ] Tutor/student prior-sharing → different model families
  - [ ] Easy quiz → per-topic difficulty calibration + audit hit-rate
  - [ ] Judge inflation (v0.2 only) → rubric-bound judge with anchors
- [ ] Caveats listed (multi-turn but bounded; markdown-only; small N; image-gen stubbed)
- [ ] **D4 done**

### D5 — Demo artifact
- [ ] Format chosen — dashboard, Loom, or both
- [ ] Shows: low-scoring tutor response + materials + failed quiz + grader catching the failure
- [ ] **D5 done**

---

## Phase 6 — The pitch test

- [ ] Sample artifact prepared: low-scoring tutor response + materials + failed quiz
- [ ] Shown to a friend at a lab
- [ ] Asked: "is this measuring something real that current models are bad at, that you'd want to RL against?"
- [ ] Answer **yes** → ship
- [ ] If "could be judge-LLM noise" → back to Phase 2 / kickoff §4 to tighten reward

---

## Open items to resolve (don't block Phase 2 but should be answered before Phase 4)

- [ ] Self-rating schema confirmed (default: 1–5 Likert × 3 axes + free-text)
- [ ] Reward weighting confirmed (default: equal-weight quiz score and self-rating)
- [ ] Turn budget cap confirmed (default: 8 student-side turns max)

---

## Notes / divergences from defaults

- _2026-05-09: kickoff alignment — switched to multi-turn, added human-in-the-loop student support, switched reward shape to LLM-generated quiz + self-rating (away from kickoff's static held-out probe), added image-gen as a stub tool in v0.1 (not deferred entirely)._
- _2026-05-09: Phase 2 wiring — `HumanStudent` deprioritized (LLMStudent first, since PI is automated); grading anchored on `vf.JudgeRubric` (PI's canonical LLM-judge format) rather than a custom interface; bumped `verifiers>=0.1.14` and switched tool defs to provider-agnostic flat dicts auto-derived via `convert_func_to_tool_def` (kickoff's "Chat Completions nested" guidance was for v0.1.5 and is stale)._
