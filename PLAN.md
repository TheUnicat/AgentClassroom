# PLAN: LLM Teaching-Quality RL Environment

Source: `TEACHING_ENV_KICKOFF.md`. Decisions resolved at kickoff alignment are reflected here. The founder's five deliverables (kickoff §3) drive the structure — every phase below is justified by the deliverable(s) it advances.

---

## Founder's 5 deliverables (the north star)

These are what we ship. Everything in this plan ladders up to one of them.

| #      | Deliverable                                                                                                     | Lands in Phase |
| ------ | --------------------------------------------------------------------------------------------------------------- | -------------- |
| **D1** | **One-page pitch** — what env measures, why current models fail, why it matters commercially                    | Phase 5        |
| **D2** | **Runnable repo** — one-command setup, README, sample task, sample rollout, sample grader output                | Phases 1–3     |
| **D3** | **Baseline report** — ≥3 models, 30–100 rollouts, pass@1/k or mean reward, failure taxonomy, 2–3 example traces | Phase 4        |
| **D4** | **Data/rubric card** — public vs held-out, what reward measures, hack surfaces, caveats                         | Phase 5        |
| **D5** | **Demo artifact** — live dashboard or short Loom showing the model failing and the grader catching it           | Phase 5        |

Pitch line: **failure-frontier framing**, not "we built an eval." Audience: friends at labs and data companies.

---

## Phase 0 — Decisions (RESOLVED)

| Question                  | v0.1 answer                                                                                                          |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Subjects                  | **Math + CS**                                                                                                        |
| Single-turn vs multi-turn | **Multi-turn**, fixed `turns: N` per task (1..N). `turns: 1` ⇒ no student LLM call.                                  |
| Source material format    | Markdown only                                                                                                        |
| Modality                  | Text-only tutor responses, **but tool-calling supported** including a stubbed image-gen tool                         |
| Student                   | LLM is the v0.1 active path; `HumanStudent` stays a stub. Each task gets its own student system prompt.              |
| Reward shape              | **LLM judge scores the full transcript against the per-task rubric.** No quiz, no self-rating in v0.1.               |
| Per-task customization    | Each task can override tutor + student system prompts AND pin specific student messages (`fixed_student_followups`). |
| Model entry point         | Very general per Prime Intellect — don't pin model names; use the `AsyncOpenAI` client Verifiers passes in           |
| Topic count for v0.1      | 10–20 hand-authored across math + CS                                                                                 |
| Public/held-out split     | All public for v0.1; revisit for v0.2                                                                                |
| Demo format (D5)          | TBD — decide later, possibly both dashboard and Loom                                                                 |
| Sibling project access    | **No access** to `~/PolicyRLEnv/` — derive Prime/Verifiers patterns from the kickoff doc only                        |

### Reward pipeline (revised 2026-05-09)
```
for turn in 1..N (per-task):
  if turn == 1: student message = task's seed_question.md (always pinned)
  else if task pinned this turn's message: use it (no student LLM call)
  else: student LLM produces follow-up given the conversation
  tutor responds (with tool access; image_gen stubbed)

after N turns:
  full transcript + materials + per-task rubric → LLM judge → JSON {scores: {criterion: 0..1}}
  reward = mean of per-criterion scores
```

Why this shape: simplest reward that exercises the failure-frontier (does the tutor scaffold, bridge to materials, diagnose gaps?), aligns with PI's `vf.JudgeRubric` format, and stays cheap. Quiz + self-rating code remains in `grader/quiz.py` and `LLMStudent.{answer_quiz, self_rate}` for re-enable when we want a reward signal harder to game than judge-only — but defer that until baselines from this shape show whether the judge alone is enough discriminating.

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

## Phase 2 — Wire up Verifiers + the reward pipeline ✓ (DONE 2026-05-09)

End-to-end live rollouts working: `turns: 3` ⇒ reward 1.000; `turns: 1` ⇒ reward 0.900 with no student LLM call. See `PROGRESS.md` for the per-checkbox status.

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
- What the reward measures: LLM judge scores the full transcript against the per-task rubric. Reward = mean of per-criterion sub-scores in [0, 1].
- Public vs held-out (v0.1: all public; rubrics + system prompts are visible to anyone running the env).
- Reward-hack surfaces:
  - **Judge inflation for confident-sounding answers.** Per-task rubrics are prose criteria; the judge can be swayed by verbosity / confident tone. Mitigation: rubrics call out what NOT to score on; v0.2 anchored examples + a stricter judge prompt.
  - **Tutor and judge share priors.** The same model family judging itself inflates scores. Use a different judge model family from any tutor under test, especially for the headline baseline numbers.
  - **Tutor sees rubric (it doesn't).** The rubric is in `info`, not in the tutor's system prompt — confirm during authoring that no task accidentally pastes the rubric into the tutor prompt.
  - **Student LLM as evaluator vs participant.** The student LLM produces follow-ups; it does NOT score. But if student and judge are the same model, biased follow-ups can shape the transcript favorably for the judge. Use different families for student and judge if budget allows.
  - **Pinned student messages reduce realism.** Tasks with all turns fixed make the env more reproducible but lose the "real student would push back here" signal. Reserve fully-pinned tasks for regression / ablation use cases.
  - **Quiz / self-rating re-enable (later).** Existing pitfalls (probe leakage, easy quiz) come back if/when we re-enable; documented in `grader/quiz.py`.
- Known caveats (v0.1: bounded `turns: N` per task; markdown-only materials; small N tasks; image-gen stubbed; same model often plays student and judge for cost reasons).

Use prose + concrete examples, not rigid structured fields.

### D5 — Demo artifact: web dashboard

**Decision (2026-05-10):** ship a dashboard (not just a Loom). Single page, two halves:

- **Left half:** task selector → rubric viewer → past-runs list → "Run fresh" button.
- **Right half:** chat / transcript view → per-criterion score breakdown + judge rationale.

Switching tasks updates the rubric pane. Selecting a past run loads its transcript + scores into the right half. Clicking "Run fresh" kicks off a new rollout against the selected task and streams the transcript back live.

**Stack (split deploy):**

```
dashboard/
├── frontend/   # Next.js 15 (App Router) + Tailwind + shadcn/ui  →  Cloudflare Pages
└── backend/    # FastAPI wrapping teachingbench.load_environment().evaluate(...)  →  HF Spaces (CPU, free)
```

Frontend talks to backend via HTTPS + SSE for live transcript streaming. Cloudflare Pages doesn't run Python (Pages Functions are JS/TS only), hence the split.

**API key handling:** server-side OpenAI key on the HF Space, no auth, security-through-obscurity is acceptable for v0.1 (low-balance OpenAI account, low public exposure). Revisit if the demo URL gets shared widely — the realistic next step is per-IP rate limiting or BYOK.

**Backend endpoints (FastAPI):**

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/tasks` | List tasks: `task_id`, `subject`, `topic`, `difficulty`, `turns`, `rubric` (with anchors) |
| `GET` | `/api/runs` | List saved rollouts (id, task_id, model, timestamp, composite reward) |
| `GET` | `/api/runs/{id}` | Full saved rollout: transcript, per-criterion scores, judge rationale |
| `POST` | `/api/run` | Trigger fresh rollout. SSE stream emits `{type: "message", role, content}` chunks; final event is `{type: "done", reward, scores, rationale}` |

**Past rollouts source:** read directly from the existing `environments/teachingbench/outputs/runs/<timestamp>__<task>__<model>/results.jsonl` files. Backend mounts that directory at startup; new rollouts append. (HF Spaces persistent disk handles this; `git`-ignored so they don't bloat the repo.)

**Frontend tech:** Next.js 15 App Router + Tailwind + shadcn/ui. Single route `/`. Components: `<TaskSelector>`, `<RubricView>`, `<RunsList>`, `<ChatView>`, `<ScorePanel>`. `lib/api.ts` for the client; SSE consumed via `EventSource` or `fetch` + `ReadableStream`.

**Acceptance:**
- Frontend deployed to a Cloudflare Pages URL.
- Backend deployed to an HF Space; `/api/tasks` returns the two sample tasks; `/api/runs` returns the saved rollouts; `/api/run` streams a fresh rollout end-to-end.
- Friend at a lab can open the URL, click around, run a fresh rollout, and see the per-criterion breakdown — all without us walking them through anything.

**Acceptance:** D1, D4, D5 done.

---

## Phase 6 — The pitch test (kickoff §10)

Run on a friend at a lab:

> Show a sample tutor transcript that scored low, the materials it was teaching off-of, and the per-criterion judge breakdown, and ask: "is this measuring something real that current models are bad at, that you'd want to RL against?"

**Yes →** ship. **"Could be judge-LLM noise" →** back to Phase 2 to tighten: re-enable the quiz path (`grader/quiz.py` is dormant), add anchored rubric examples, swap to a different judge model family.

**Total time-to-shippable-v0.1: ~2–3 weeks** (per kickoff §9), now that Phase 0 is decided cleanly.

---

## Notes on what's still open

These don't block Phase 3 but should get answers before Phase 4:

- **Per-task `turns` defaults.** What's a good default for math vs CS topics? Some concepts are 1-turn ("explain factorial"); some need 4–6 turns of back-and-forth. Phase 4 authoring will calibrate per-topic.
- **Per-task rubric authoring.** First sample task has a custom rubric (clarity / diagnosis / bridging / transfer). Decide whether subjects share a common rubric template or each task gets its own — probably "shared default + per-task overrides where the failure mode is specific."
- **Quiz / self-rating re-enable trigger.** Re-enable when transcript-judge baselines saturate or look noisy. Until then, code stays in repo unused.
- **Convert env messages to `vf.UserMessage` / `vf.ToolMessage`.** Verifiers warns about repeated `normalize_messages` overhead; functional but inefficient. Polish before Phase 3 push.
- **Student readiness on free-form runs.** Not relevant in current design (turns are fixed), but worth keeping in mind if we re-enable a "student decides" mode later.
- **Prior intern's repo.** First-version teaching benchmark exists at <https://github.com/hujalex/teaching-benchmark> — borrow ideas (parsing approaches, NLP libs they tried), don't fork.
