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

> **Reward shape (revised 2026-05-09):** fixed `turns: N` per-task chat loop → full transcript scored by an LLM judge against the task's rubric. **No quiz, no self-rating** in the active path (code kept around for re-enable). Student LLM produces follow-ups every turn — no "ready" decision, no early termination. `turns: 1` ⇒ no student LLM call. Each task can override tutor + student system prompts and pin specific student messages.
>
> Grading uses `vf.JudgeRubric` (PI's canonical LLM-judge format). Verifiers v0.1.14 — tool defs are auto-derived via `convert_func_to_tool_def`.

### Env subclass
- [x] `TeachingEnv` subclasses `verifiers.MultiTurnEnv`
- [x] `setup_state(state)` loads per-task fields (turns, materials, topic, rubric, tutor + student system prompts, fixed_student_followups) and injects the per-task tutor system prompt
- [x] `env_response(messages, state)` drives the dialog: tool-dispatch → fixed student message OR student LLM `respond` → finalize when `completed_turns >= turns`
- [x] Termination via `state["final_env_response"]` (the `@vf.stop has_final_env_response` predicate); no message-content heuristics
- [x] `rollout(...)` not overridden (it's `@final` in MultiTurnEnv anyway)
- [x] `turns: 1` ⇒ no student LLM call (verified live: tutor responds once, finalize, reward 0.9 in test)
- [x] `fixed_student_followups[i]` covers turn (i+2); shorter list falls through to student LLM

### Internal model calls
- [x] LLMStudent and the transcript judge use an `AsyncOpenAI` client + model — stored on `self._student_client` / `self._judge_client` directly (NOT looked up via `env.rubric`, since MultiTurnEnv wraps it in a RubricGroup)
- [x] No tutor model names hardcoded; tutor model flows from Verifiers' `client`/`model` rollout args. Env-side LLM defaults to `gpt-5.4-nano` (overridable via `load_environment`); judge sampling temperature defaults to 0.2 for grader determinism
- [x] Per-task tutor + student system prompts; defaults interpolate `{materials}` and `{topic}`

### Student
- [x] `LLMStudent.respond` — produces next student message given the conversation; no decision branching
- [x] `Student` Protocol — active method is `respond`; `decide`/`answer_quiz`/`self_rate` kept around as legacy
- [ ] `HumanStudent.*` — **deferred** (LLM-first per kickoff alignment)

### Grader
- [x] `TeachingRubric(vf.JudgeRubric)` — reward func calls the judge LLM with rubric + materials + transcript, parses JSON, averages per-criterion scores
- [x] Per-task rubric loaded from `rubric.md`, with a sensible default fallback in `prompts.DEFAULT_RUBRIC`
- [x] `transcript_score` is the headline reward (weight 1.0); `num_rubric_criteria` is a zero-weight metric so we can spot rubric mismatches
- [x] `state["judge_breakdown"]` caches the parsed sub-scores + rationale
- [x] **Quiz / self-rating code kept** in `grader/quiz.py` and `LLMStudent.{answer_quiz, self_rate}` for re-enable later — not wired into env_response

### Tools
- [x] `image_gen` stub authored as a function; tool def auto-derived via `convert_func_to_tool_def`
- [x] Tool dispatch wired into `env_response` — checks `messages[-1].tool_calls`, dispatches via `_tool_map`, returns `ToolMessage`s

### Dataset
- [x] `dataset.py` — discovers tasks from `tasks/<subject>/<topic>/`, loads `meta.yaml` + `seed_question.md` + `materials/*.md` + optional `rubric.md`
- [x] `info` column serialized as JSON string (flat schema; HF won't reject mixed shapes)
- [x] Per-task fields: `turns`, `tutor_system_prompt`, `student_system_prompt`, `fixed_student_followups`, `rubric` (all optional with defaults)
- [x] No plain-string `task` column (verifiers v0.1.14 rejects it)
- [x] Sample tasks authored:
  - `cs/recursion_base_cases/` — `turns: 3`, with materials/, per-task `rubric.md` (clarity / diagnosis / bridging / transfer)
  - `cs/intro_python_hello_world/` — `turns: 4`, **no materials**, custom tutor + student prompts (student is a confederate beginner with Python installed), per-task `rubric.md` (diagnosis / anti_firehose / skill_appropriate / scaffolding); seed message verbatim per HUMAN_SCRATCHPAD.md. **Not yet tested live** (per user request).

### Smoke test
- [x] Argparse: `--task`, `--tutor-model`, `--judge-model`, `--base-url`, `--api-key-env`, `--default-turns`, `--live`
- [x] `--dry-run` (default) builds dataset + imports env + lists tools + prints per-task config (turns, prompt lengths, rubric length)
- [x] `--live` runs a full rollout via `env.evaluate(client=ClientConfig(...), model=..., num_examples=1, rollouts_per_example=1)`
- [x] **Acceptance:** end-to-end rollout printed score breakdown — **DONE 2026-05-09**. Two live runs with `gpt-4.1-nano` for both tutor and env-side LLM:
  - `turns: 3` → reward `1.000` (judge full marks across 4 criteria), 3/3 turns completed, stop_condition `has_final_env_response`.
  - `turns: 1` → reward `0.900`, 1/1 turn completed, **no student LLM call** confirmed (only tutor + seed in the trajectory).

---

## Phase 3 — Push v0.1.0 to Prime Intellect (D2 complete)

### Polish before push
- [x] Updated stale references — `pyproject.toml` description, env-level `README.md`, dry-run "Rubric" label all now reflect the transcript-judge reward design
- [x] Verified live runs on both sample tasks (`intro_python_hello_world` + `recursion_base_cases`) under structured-rubric + null-bridging
- [ ] _Optional polish (non-blocking):_ convert `env_response` / `_finalize` / `setup_state` to typed `vf.UserMessage` / `vf.ToolMessage` to silence verifiers `normalize_messages` perf warnings

### Local wheel verification (DONE 2026-05-10)
- [x] `pip wheel environments/teachingbench --no-deps -w /tmp/teachingbench_wheel` succeeds (32 KB wheel)
- [x] `unzip -l` confirms tasks/ data files included (both `meta.yaml` files + recursion `materials/*.md`)
- [x] `pip install --force-reinstall /tmp/teachingbench_wheel/teachingbench-0.1.0-py3-none-any.whl` succeeds
- [x] `cd /tmp && python -m teachingbench.smoke_test` runs cleanly — no source-tree dependency

### Push (USER STEP — needs `prime` auth)
- [ ] `prime env push --path environments/teachingbench` exits clean
- [ ] **Metadata test confirmed passing on Prime dashboard** (CLI exit-success NOT sufficient)
- [ ] v0.1.0 visible on Prime with both sample tasks runnable
- [ ] `prime eval run` skipped (needs billing; smoke test covers local dev)

---

## Phase 4 — Author tasks + baselines (D3)

### Authoring
- [ ] 10–20 tasks across math + CS subjects
- [ ] Each task: optional materials/, seed_question.md, meta.yaml with `turns` and difficulty, optional `rubric.md` (else default rubric)
- [ ] Per-task `turns` calibrated (1-turn for "explain X" prompts; 4–6 for back-and-forth concepts)

### Reliability checks (BEFORE running headline baselines)

Two kinds — both needed before Phase 4 numbers are trustworthy.

**A) Judge reliability — same judge replays same transcript N times**
- [x] `grader/judge.py` refactored to expose public `judge_transcript()` helper (pure async function, no state mutation)
- [x] `environments/teachingbench/teachingbench/reliability_check.py` — argparse CLI, parallel `asyncio.gather` of N judge calls
- [x] CLI: `python -m teachingbench.reliability_check <run_id> --n 8 [--judge-model ...]`
- [x] Reports per-criterion + composite: `n_scored/n`, `min`, `max`, `range`, `median`, `mean`, `stdev`, `CV`
- [x] **First run, 2026-05-10:** `gpt-5.4-nano` judge (temp 0.2), n=8, on `20260510T143355Z__cs__intro_python_hello_world` (reward 0.867, current default rubric). Composite CV=0.039 (very stable). All scored criteria CV ≤ 0.062. `bridging` null on 8/8 trials (perfect agreement on the N/A call). Composite range: 0.767–0.850. Original saved reward of 0.867 was at the high end → single-shot scores carry ~±0.04 noise even at low CV.
- [x] **Second run, 2026-05-10:** same judge config, n=8, on `20260509T164146Z__cs__intro_python_hello_world` (reward 0.625, OLD per-task rubric: diagnosis/anti_firehose/skill_appropriate/scaffolding). Composite CV=0.100 (acceptable) but per-criterion variance is bimodal:
  - `diagnosis` and `skill_appropriate` saturate (CV=0.000): judge nails them on every trial.
  - `anti_firehose` is **wildly noisy** (CV=0.307, range 0.5–1.0). Judge can't decide if the same transcript was firehosing or not.
  - `scaffolding` is medium-noisy (CV=0.197, range 0.5–0.8).
  - Original saved score 0.625 was at the LOW end of the new distribution (mean 0.706, range 0.625–0.800). Confirms single-shot scores under-report as easily as over-report.
  - **Takeaway:** the composite looks fine but masks per-criterion problems. `anti_firehose` is the rubric criterion most in need of tightened anchors / concrete length thresholds. Subjective/spectrum criteria are noisier than objective/yes-no criteria.

**B) Inter-trial rollout reliability — same task, multiple full rollouts**
- [ ] Script that reruns each task N times (fresh tutor + student LLM each time), reports per-task reward variance
- [ ] Define a variance threshold above which a task is considered too noisy to use
- [ ] Tighten rubric or task content for any task that exceeds the threshold

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

### D5 — Demo artifact: web dashboard

> Decision 2026-05-10: ship a dashboard. Split deploy — frontend on Cloudflare Pages (Next.js), backend on HF Spaces (FastAPI). Single page, two halves: task picker + rubric on the left, chat + scores on the right. Server-side OpenAI key, no auth, security-through-obscurity.

#### Backend (FastAPI on HF Spaces)
- [ ] `dashboard/backend/app.py` — FastAPI app
- [ ] `GET /api/tasks` — lists tasks with full rubric (id, description, anchors)
- [ ] `GET /api/runs` — lists saved rollouts (id, task, model, timestamp, composite reward)
- [ ] `GET /api/runs/{id}` — full rollout: transcript, per-criterion scores, rationale
- [ ] `POST /api/run` — SSE stream of fresh rollout (turn-by-turn messages, then final scores)
- [ ] `dashboard/backend/requirements.txt` — fastapi, uvicorn, sse-starlette, openai, datasets, pyyaml, verifiers, teachingbench (editable / wheel)
- [ ] `dashboard/backend/Dockerfile` (or HF `app.py` convention) — for HF Space build
- [ ] CORS configured for the Cloudflare Pages domain
- [ ] OpenAI key read from `OPENAI_API_KEY` env var (HF Space secret)
- [ ] Saved-runs source: reads from `environments/teachingbench/outputs/runs/` (mounted or copied at deploy)
- [ ] `dashboard/backend/README.md` — local-dev + HF Space deploy steps

#### Frontend (Next.js 15 App Router on Cloudflare Pages)
- [ ] `dashboard/frontend/` — Next.js 15 + Tailwind + shadcn/ui scaffold
- [ ] Single page `app/page.tsx` with 50/50 left-right layout
- [ ] Left half: `<TaskSelector>` → `<RubricView>` → `<RunsList>` → "Run fresh" button
- [ ] Right half: `<ChatView>` (transcript) → `<ScorePanel>` (per-criterion + rationale)
- [ ] `lib/api.ts` — typed client for backend endpoints
- [ ] SSE consumer for `/api/run` (`EventSource` or `fetch` + `ReadableStream`)
- [ ] `NEXT_PUBLIC_BACKEND_URL` env var pointing at the HF Space
- [ ] `dashboard/frontend/README.md` — local-dev + Cloudflare Pages deploy steps

#### Acceptance
- [ ] Backend running locally on `:8000`, all 4 endpoints respond
- [ ] Frontend running locally on `:3000`, can browse + run rollouts via local backend
- [ ] Backend deployed to an HF Space (URL noted)
- [ ] Frontend deployed to a Cloudflare Pages URL (URL noted)
- [ ] **End-to-end test:** open the Cloudflare URL, click intro_python, click "Run fresh," see transcript stream, see scores at the end
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
- _2026-05-09: Phase 2 live test — passed with `composite=0.833`. Verifiers v0.1.14 surprises encountered and resolved: tutor client must be `ClientConfig` not raw `AsyncOpenAI`; `evaluate` takes `num_examples` not `num_rollouts`; dataset can't have a plain-string `task` column; `MultiTurnEnv` wraps your rubric in a `RubricGroup`, so don't look up env-side LLM clients via `env.rubric` — store on `self._*` instead. All gotchas saved to memory under `feedback_verifiers_v014_api_gotchas.md`._
- _2026-05-09: Open issue (non-blocking) — `env_response`/`get_prompt_messages` return raw dicts, triggering verifiers warnings about repeated `normalize_messages()` overhead. Functional but inefficient; convert to `vf.UserMessage`/`vf.ToolMessage` types when polishing for Phase 3._
- _2026-05-09: Open issue (Phase 4 follow-up) — student LLM never signaled "ready" within 8 turns on the live test; hit turn cap. Tune the student prompt to encourage earlier readiness, otherwise rollouts are needlessly expensive._
- _2026-05-09: Reward-shape pivot — dropped quiz + self-rating from the active path. Reward = LLM judge scores the full chat transcript against the per-task rubric. `turns: N` per task now drives the loop length (no early-termination decision from the student). Each task can override tutor + student system prompts and pin specific student messages. Quiz/self-rating code kept in repo (`grader/quiz.py`, `LLMStudent.answer_quiz`/`self_rate`) but unused. Live verified: `turns: 3` ⇒ reward 1.000; `turns: 1` ⇒ reward 0.900 with no student LLM call._
- _2026-05-09: Model defaults bumped from `gpt-4.1-nano` → `gpt-5.4-nano` for env-side LLM (judge + simulated student); judge sampling temperature 0.0 → 0.2 per HUMAN_SCRATCHPAD.md. Updated in `env.py`, `grader/judge.py`, `smoke_test.py`. Reasoning: even frontier models teach poorly, so don't sandbag the env-side LLM with an older generation just because the kickoff doc happened to use it. Saved as a feedback memory._
- _2026-05-09: New sample task `cs/intro_python_hello_world` added — no materials, custom tutor + student prompts (student is a Python-installed but never-coded confederate), strict 4-criterion rubric (diagnosis / anti_firehose / skill_appropriate / scaffolding), seed message pinned verbatim. Not yet tested live (per user)._
- _2026-05-09: Open follow-up surfaced from HUMAN_SCRATCHPAD.md — need a reliability-check script that reruns each task N times with fixed seeds and reports inter-trial reward variance. High variance ⇒ task / rubric needs tightening before it can land in baseline report. Saved as a project memory._
