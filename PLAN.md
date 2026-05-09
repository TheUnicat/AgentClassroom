# PLAN: LLM Teaching-Quality RL Environment

Source: `TEACHING_ENV_KICKOFF.md`. Decisions resolved at kickoff alignment are reflected here. The founder's five deliverables (kickoff §3) drive the structure — every phase below is justified by the deliverable(s) it advances.

---

## Founder's 5 deliverables (the north star)

These are what we ship. Everything in this plan ladders up to one of them.

| # | Deliverable | Lands in Phase |
|---|---|---|
| **D1** | **One-page pitch** — what env measures, why current models fail, why it matters commercially | Phase 5 |
| **D2** | **Runnable repo** — one-command setup, README, sample task, sample rollout, sample grader output | Phases 1–3 |
| **D3** | **Baseline report** — ≥3 models, 30–100 rollouts, pass@1/k or mean reward, failure taxonomy, 2–3 example traces | Phase 4 |
| **D4** | **Data/rubric card** — public vs held-out, what reward measures, hack surfaces, caveats | Phase 5 |
| **D5** | **Demo artifact** — live dashboard or short Loom showing the model failing and the grader catching it | Phase 5 |

Pitch line: **failure-frontier framing**, not "we built an eval." Audience: friends at labs and data companies.

---

## Phase 0 — Decisions (RESOLVED)

| Question | v0.1 answer |
|---|---|
| Subjects | **Math + CS** |
| Single-turn vs multi-turn | **Multi-turn** — student can ask follow-ups before being quizzed |
| Source material format | Markdown only |
| Modality | Text-only tutor responses, **but tool-calling supported** including a stubbed image-gen tool |
| Student | LLM by default, **must also support human-in-the-loop** (student-in-the-loop verification, not pure self-play) |
| Reward shape | **LLM-generated quiz + student self-rating** (replaces the kickoff's held-out-probe-only design). Judge LLM is v0.2. |
| Model entry point | Very general per Prime Intellect — don't pin model names; use the `AsyncOpenAI` client Verifiers passes in |
| Topic count for v0.1 | 10–20 hand-authored across math + CS |
| Public/held-out split | All public for v0.1; revisit for v0.2 |
| Demo format (D5) | TBD — decide later, possibly both dashboard and Loom |
| Sibling project access | **No access** to `~/PolicyRLEnv/` — derive Prime/Verifiers patterns from the kickoff doc only |

### Reward pipeline
```
tutor teaches (multi-turn, with tool access)
    → grader generates quiz (LLM, post-teaching, targets what was actually taught)
    → student answers + self-rates
    → reward = quiz score + self-rating  (weighting TBD; start equal-weighted)
```

This shape is harder to reward-hack than judge-only AND avoids the leakage problem of static held-out probes (because the quiz is generated *after* teaching, conditioned on what the tutor actually said).

---

## Phase 1 — Skeleton ✓ (DONE)

Repo scaffolding so verifiers, tasks, and control flow can drop in.

What landed:
- Top-level: `README.md`, `.gitignore`, `.prime/lab.json`
- `environments/teachingbench/pyproject.toml` — hatchling, `tags`, deps for verifiers/openai/datasets, optional `materials` extras (markitdown, frontmatter)
- `environments/teachingbench/README.md` — env-level
- `teachingbench/__init__.py` exposing `load_environment`
- Stubs: `env.py` (TeachingEnv class shell), `smoke_test.py` (argparse + asyncio shell)
- `student/` — `Student` Protocol + `LLMStudent` and `HumanStudent` stubs
- `grader/` — `quiz.py` (`generate_quiz`, `score_quiz`) + `judge.py` (v0.2 stub)
- `tools/` — Chat Completions tool registry + `image_gen` stub tool
- `tasks/README.md` — authoring layout

---

## Phase 2 — Wire up Verifiers + the reward pipeline

Goal: a single end-to-end task runs through `prime env push` plumbing locally.

### Sub-steps

1. **TeachingEnv subclass** — make `env.py` actually subclass `verifiers.MultiTurnEnv`. Implement `setup_state` (load materials + opening student question into state), `env_response` (drive the multi-turn dialog: when tutor finishes, switch to grader-generates-quiz, then student-answers, then self-rate), `is_completed` (reward computed and finalized).
2. **Student implementations** — fill in `LLMStudent.ask/answer_quiz/self_rate` (async OpenAI calls with the env's client) and `HumanStudent.ask/answer_quiz/self_rate` (CLI prompts; UI adapter is a v0.2 nicety).
3. **Grader implementations** — `generate_quiz` produces 3–5 MCQ + 1 free-response targeting what the tutor actually taught (use the teaching trace + materials as conditioning). `score_quiz` computes per-item correctness and combines with self-rating.
4. **Tool dispatch in env** — when the tutor's response includes tool calls, dispatch via `tools.schemas.dispatch` and feed results back. Image-gen returns the stub payload.
5. **Dataset construction** — build the dataset row from one task: `prompt` (chat list with system message included; `format_dataset` won't auto-prepend), `info` (flat schema; serialize variable-shape per-task data as JSON strings).
6. **Smoke test** — argparse for tutor model / student type / task ID; runs one rollout end-to-end and prints conversation tail + score breakdown.

**Acceptance:** `python -m teachingbench.smoke_test --task math/<topic> --tutor-model <m> --student llm` runs tutor (multi-turn) → quiz → student answers → self-rate → score, end-to-end, with at least one tool call exercised.

---

## Phase 3 — Push v0.1.0 to Prime Intellect (D2 complete)

### Pre-push wheel verification
```bash
pip wheel environments/teachingbench --no-deps -w /tmp/wheel_test
unzip -l /tmp/wheel_test/teachingbench-0.1.0-py3-none-any.whl
pip install --force-reinstall /tmp/wheel_test/teachingbench-0.1.0-py3-none-any.whl
cd /tmp && python -m teachingbench.smoke_test
```

### Push
- `prime env push --path environments/teachingbench`
- Verify metadata test on the **Prime dashboard**, not just CLI exit code
- Skip `prime eval run` (needs Prime Inference billing; smoke test covers local dev)

**Acceptance:** v0.1.0 live on Prime with one runnable task.

---

## Phase 4 — Author tasks + baselines (D3)

- **10–20 tasks** across math + CS. Each: source materials (markdown), opening question, difficulty band. Calibrate difficulty per topic so easy-probe reward hack is closed off.
- **Baseline lineup:** keep the model entry point general per Prime — don't hardcode. Run **≥3 capability-stratified models** (e.g., one frontier, one mid-tier, one small). Confirm the LLM student is a different model family from any tutor under test (avoids prior-sharing inflating quiz scores).
- **30–100 rollouts** total. Save: full trace, tool calls, generated quiz, student answers, self-rating, per-rollout reward.
- **Failure taxonomy** drafted from traces (firehose / no diagnosis / ignores materials / weak/no diagram-call when needed / leaks quiz answers verbatim during teaching / over-confident self-rating disagrees with quiz score / etc.).
- **2–3 example traces** picked: one obvious failure, one near-miss, one clean win.

**Acceptance (D3 done):** baseline numbers + failure taxonomy + traces written up.

---

## Phase 5 — Pitch, rubric card, demo (D1, D4, D5)

### D1 — One-page pitch
Lead with the failure-frontier line. Concrete failure mode → trace as evidence → why it matters commercially (AI tutoring vertical, lab need for teaching reward models, EdTech buyer path through NWEA MAP / formative assessments).

### D4 — Data/rubric card
- What the reward measures (quiz score + self-rating; weighting; what they each capture).
- Public vs held-out (v0.1: all public; quizzes are generated post-hoc not stored).
- Reward-hack surfaces (kickoff §4):
  - **Tutor leaks quiz answers** during teaching → quiz is post-teaching and conditioned on the trace, but the *materials* are visible to both tutor and quiz-generator; flag if quiz items are too verbatim with the materials.
  - **Self-rating gaming** → check correlation between self-rating and quiz score; flag rollouts where the gap is unusually large (could indicate either a confused student or a sycophantic tutor).
  - **Tutor and student share priors** → use different model families.
  - **Easy quiz** → calibrate difficulty per topic and audit per-topic quiz hit-rate.
  - **Judge inflation (v0.2)** → rubric-bound judge with anchored examples when judge LLM is added.
- Known caveats (v0.1: multi-turn but bounded turn count; markdown-only materials; small N; image-gen stubbed).

Use prose + concrete examples, not rigid structured fields.

### D5 — Demo artifact
- Format TBD — possibly both. Dashboard reference: <https://meeting-intent-dashboard.vercel.app/>.
- Must show: a tutor response that scored low + the materials it was teaching off + the quiz the student failed + the grader catching it.

**Acceptance:** D1, D4, D5 done.

---

## Phase 6 — The pitch test (kickoff §10)

Run on a friend at a lab:

> Show a sample tutor response that scored low, the materials it was teaching off-of, the quiz the student failed, and ask: "is this measuring something real that current models are bad at, that you'd want to RL against?"

**Yes →** ship. **"Could be judge-LLM noise" →** back to Phase 2 to tighten the reward (e.g., add the v0.2 weighted judge, tighten quiz difficulty calibration, or revisit self-rating weighting).

**Total time-to-shippable-v0.1: ~2–3 weeks** (per kickoff §9), now that Phase 0 is decided cleanly.

---

## Notes on what's still open

These don't block Phase 2 but should get answers before Phase 4:

- **Self-rating schema.** Single Likert? Multi-dimensional (clarity / coverage / confidence-i-could-do-it-myself)? Free-text + extracted? Default proposal: 1–5 Likert across 3 axes (clarity, coverage, confidence) + one free-text "what's still confusing."
- **Reward weighting.** Equal-weight quiz score and self-rating to start; revisit after Phase 4 traces show whether they correlate or diverge usefully.
- **Turn budget.** Cap multi-turn dialog at e.g. 8 student-side turns to prevent infinite back-and-forth from inflating cost / blowing up the env.
- **Prior intern's repo.** First-version teaching benchmark exists at <https://github.com/hujalex/teaching-benchmark> — borrow ideas (parsing approaches, NLP libs they tried), don't fork.
