# PROGRESS: Decoupled / Deterministic Judging Overhaul

Step-by-step checklist for `PLAN_v2.md`. Mark `[x]` when done.

---

## Phase 1 — Skeleton (no behavior change)  ✅

- [x] Create `teachingbench/grader/functions/{llm,deterministic}/` with `__init__.py`s
- [x] Create `teachingbench/grader/composers/` with `__init__.py`
- [x] Write `functions/base.py` — `Deterministic` and `LLM` protocols
- [x] Write `composers/base.py` — `Composer` protocol + default formula wrapper around `reward_scoring.compute_composite`
- [x] Wrap existing `judge_transcript` as `composers/v1_llm_only.py` (no behavior change)
- [x] Sanity check: run v1_llm_only on 2–3 saved rollouts, eyeball scores match the originals (±LLM noise)
       → 3/3 within Δ=±0.011 of the original composite (target ±0.1)
- [x] Build `grader/runner.py` CLI: `python -m teachingbench.grader.runner --composer v1_llm_only path/to/results.jsonl`
- [x] Confirm runner writes `judge_breakdown__<composer>` keys without touching the original `judge_breakdown`
- [x] Confirm dashboard still works (Demo + Results both untouched — no edits to existing files)
- [x] Commit

---

## Phase 2 — Implement judge functions

**Deterministic, first pass:**
- [ ] `sycophancy_regex`
- [ ] `anti_firehose_length`
- [ ] `first_message_length`
- [ ] `echo_score`
- [ ] `seed_question_recall`
- [ ] `turn_asymmetry`
- [ ] `listicle_density`
- [ ] `question_density`

**Deterministic, second pass:**
- [ ] `flesch_kincaid`
- [ ] `code_validity`
- [ ] `concept_velocity`
- [ ] `type_token_ratio`

**LLM (refactored):**
- [ ] Split each current rubric criterion into its own `functions/llm/*.py`
- [ ] New: `reward_hack_detector`

---

## Phase 3 — Teacher system prompts + composers

**Prompts (`prompts.py`):**
- [ ] `CONCISE_TEACHER`
- [ ] `SOCRATIC_TEACHER`
- [ ] `MATERIALS_GROUNDED_TEACHER`
- [ ] `HUMBLE_TEACHER`
- [ ] Plumb `tutor_system_prompt` override via task metadata + CLI flag

**Composers:**
- [ ] `v2_hybrid` — LLM (semantic) + deterministic (mechanical) + reward-hack cap
- [ ] `v3_deterministic` — pure deterministic, RL-fast

---

## Phase 4 — Verify

- [ ] Determinism: v3 produces identical scores when run twice on the same rollout
- [ ] Hand-spot-check 10 rollouts against v2_hybrid; tune weights
- [ ] Agreement: v1 vs v2 on 30 rollouts; document disagreements
- [ ] Reward-hack stress test: 3–4 hand-crafted bad-teacher transcripts, v2 + v3 catch them
- [ ] Edge cases: empty rollout, single-turn, math+image, all-N/A criteria

---

## Phase 5 — Re-judge the 228 + report

- [ ] Run `runner.py` over the 228 with v1, v2, v3 (three new `judge_breakdown__*` keys per row)
- [ ] Aggregate by model under each composer; diff against baseline_report
- [ ] (Optional) re-run 30–50 with `CONCISE_TEACHER` / `SOCRATIC_TEACHER` prompts
- [ ] Update report (or land `baseline_report_v2.md`); surface in dashboard's Full Report tab
- [ ] Dashboard: composer-picker on Results page
- [ ] Commit + redeploy
