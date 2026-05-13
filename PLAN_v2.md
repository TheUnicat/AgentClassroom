# PLAN for v2: Decoupled / Deterministic Judging Overhaul

A parallel scoring system. Adds deterministic judge functions alongside the
existing LLM rubric, with maximum modularity: each judge is its own file, each
**composer** picks a combination and assigns weights. Running and judging are
**severed** — a rollout is produced once and can be judged (or re-judged) by
any composer afterwards.

Side bundle: teacher system-prompt variants, so we can study how teaching
behavior shifts under explicit guidance and re-evaluate with the new judging
stack.

Composer output gets written to `results.jsonl` as a new
`judge_breakdown__<composer-name>` key alongside the existing
`judge_breakdown`, so v1 / v2 / v3 scores live side-by-side on every rollout.

---

## Architecture

```
teachingbench/grader/
├── functions/                  # one file per judge function
│   ├── base.py                 # protocols: Deterministic, LLM
│   ├── llm/                    # async, takes a judge_client
│   │   ├── answers_the_question.py
│   │   ├── factual_correctness.py
│   │   ├── meeting_student_level.py
│   │   ├── bridging.py
│   │   ├── clarity.py
│   │   ├── scaffolding.py
│   │   └── reward_hack_detector.py    # NEW (meta-check)
│   └── deterministic/          # pure-Python, no LLM, no I/O
│       ├── sycophancy_regex.py
│       ├── anti_firehose_length.py
│       ├── first_message_length.py
│       ├── echo_score.py
│       ├── seed_question_recall.py
│       ├── turn_asymmetry.py
│       ├── listicle_density.py
│       ├── question_density.py
│       ├── flesch_kincaid.py
│       ├── code_validity.py
│       ├── concept_velocity.py
│       └── type_token_ratio.py
├── composers/                  # one file per scoring config
│   ├── base.py                 # Composer protocol + default formula
│   ├── v1_llm_only.py          # current baseline (LLM rubric, no change)
│   ├── v2_hybrid.py            # LLM (semantic) + deterministic (mechanical)
│   └── v3_deterministic.py     # pure deterministic — fast RL reward proxy
├── reward_scoring.py           # convex_revquad math (unchanged)
└── runner.py                   # CLI: re-judge a results.jsonl with any composer
```

### Contracts

**Deterministic function** — `functions/deterministic/<x>.py`:
```python
def score(messages: list[dict], task_info: dict) -> float | None:
    """Pure. Returns a [0, 1] score or None (N/A). No I/O."""
```

**LLM function** — `functions/llm/<x>.py`:
```python
async def score(messages, task_info, *, judge_client, judge_model) -> dict:
    """Returns {value: float | None, rationale: str, raw: dict}."""
```

**Composer** — `composers/<name>.py`:
```python
NAME = "v2_hybrid"
WEIGHTS = {"factual_correctness": 0.20, "anti_firehose_length": 0.15, ...}

async def score(messages, task_info, *, judge_client=None) -> dict:
    """Returns {scores, weights, composite, composite_raw, terms, formula, ...}."""
```

The composite math defaults to `reward_scoring.compute_composite()` but a
composer can override (its file is the natural place — equation lives next to
the weights that drive it).

### Modularity discipline

- `functions/deterministic/` must **not** import `verifiers`, OpenAI, or
  anything else teachingbench-specific. Only stdlib + small helper utilities.
  This lets us lift the whole subtree into a standalone judging-only repo if we
  want, with zero changes.
- `functions/llm/` may import `openai` / `anthropic` clients but nothing
  teachingbench-specific (it gets `task_info` as a dict, prompts as args).
- `composers/` is the only place that knows about specific judge functions and
  weights. Composer files are short and readable.

### Severing run vs judge

- **Existing path stays default** for backwards compat and the dashboard: when
  `env.evaluate()` runs, it judges in-line and writes `judge_breakdown` (v1
  output, same as today).
- **Post-hoc path**: `python -m teachingbench.grader.runner --composer v2_hybrid
  path/to/results.jsonl` reads each row, applies the composer, and appends
  `judge_breakdown__v2_hybrid` to that row. Original `judge_breakdown` is never
  overwritten.
- **Skip-judging path** (later, optional): an `env.evaluate(skip_judging=True)`
  flag for cheaper rollout-only runs.

---

## Phase 1 — Skeleton (no behavior change)

Goal: shape of the architecture without touching scores.

- Create folders + empty `__init__.py`s
- `functions/base.py` — protocols
- `composers/base.py` — Composer protocol + default formula wrapper
- Wrap existing `judge_transcript` as `composers/v1_llm_only.py` (same rubric,
  same equation, same prompt — should reproduce current scores within judge
  noise on a sanity-check rollout)
- Build `runner.py` (CLI) that takes a results.jsonl and a composer name; writes
  `judge_breakdown__<name>` keys without overwriting the originals
- Smoke-test v1_llm_only on 2-3 saved rollouts; eyeball that the new scores
  match the originals (within ~±0.1 noise)
- Dashboard untouched in this phase (it still uses the in-line v1 judge)
- Commit

---

## Phase 2 — Implement judge functions

Highest-leverage first.

**Deterministic — first pass** (each ~30–80 lines):
1. `sycophancy_regex` — phrase-list match → fraction of teacher turns with hits
2. `anti_firehose_length` — mean teacher words/turn vs target band
3. `first_message_length` — opening teacher message word count (firehose
   concentrates in turn 1)
4. `echo_score` — n-gram overlap of teacher with student's prior turn (active
   listening / "did you actually read me?")
5. `seed_question_recall` — keyword recall in final teacher message
6. `turn_asymmetry` — teacher / student word ratio per turn
7. `listicle_density` — bullets and headers per word
8. `question_density` — teacher questions toward student per turn

**Deterministic — second pass:**
9. `flesch_kincaid` — readability matched to task difficulty band
10. `code_validity` — for code tasks, do the fences parse / lint? (None for
    non-code tasks)
11. `concept_velocity` — unique-noun rate per turn (steady ramp = good
    scaffolding signal; spike then flat = info-dump)
12. `type_token_ratio` — vocab diversity (catches both jargon-dumps and
    over-simplified loops)

**LLM — refactored from current rubric:**
- One file per existing criterion, with that criterion's prompt isolated so it
  can be tuned independently
- New: `reward_hack_detector` — narrow prompt asking "is this clearly bullshit
  or gaming the judge?" — returns 0 or 1. Used as a *cap* in composers, not a
  weighted term.

---

## Phase 3 — Teacher system prompts + composers

Co-located because they exercise each other.

**Teacher system prompts** (`prompts.py`):

Currently `DEFAULT_TUTOR_SYSTEM_PROMPT = ""` — teacher gets no guidance. Add
named variants:

- `CONCISE_TEACHER` — explicit anti-firehose, max ~100 words per turn,
  forbidden listicle dumps in turn 1
- `SOCRATIC_TEACHER` — ask one short question before explaining
- `MATERIALS_GROUNDED_TEACHER` — when materials are present, must cite a
  specific passage
- `HUMBLE_TEACHER` — explicit "I'm not sure" / no excessive validation framing
  (companion piece to sycophancy detection)

Plumb via the existing `tutor_system_prompt` task override path + a CLI flag on
re-runs, so we can ablate teacher conditioning while reusing the same
composers.

**Composers:**

- `v1_llm_only` — already built in Phase 1
- `v2_hybrid` —
  - LLM: `answers_the_question`, `factual_correctness`, `meeting_student_level`,
    `bridging`, `scaffolding` (semantic things only LLMs can grade)
  - Deterministic: `anti_firehose_length`, `sycophancy_regex`,
    `first_message_length`, `listicle_density` (mechanical things LLMs grade
    unreliably)
  - `reward_hack_detector` runs as a hard cap (if it fires, composite ≤ 0.3)
  - Weights chosen to roughly match the current implicit weighting; documented
    in the composer file
- `v3_deterministic` — only deterministic functions. Fast RL reward proxy:
  ~10ms per rollout vs ~10s for LLM-based composers. The composition of
  `anti_firehose + sycophancy + first_msg_length + echo_score + seed_recall`
  picks up a lot of the failure-mode signal without an LLM call.

---

## Phase 4 — Verify

- **Determinism sanity**: re-judging the same rollout twice with v3 yields
  identical scores (proves the deterministic functions are pure)
- **Hand-spot-check**: pick 10 rollouts spanning the v1 score range (0.2–0.9),
  read v2_hybrid scores against the transcript, adjust weights/thresholds
- **Agreement check**: v1 vs v2 on 30 rollouts. The interesting rollouts are
  the disagreements — that's where pure-LLM was either too lenient (gaming) or
  too strict (penalizing structure the deterministic side approves of)
- **Reward-hack stress test**: hand-craft 3–4 obvious bad-teacher transcripts
  (sycophantic, overconfident hallucination wrapped in confident style, pure
  listicle dump). Confirm v2 / v3 catch them. Document any v1 misses.
- **Edge cases**: empty rollout, single-turn, math task with embedded images,
  all-N/A criteria

---

## Phase 5 — Re-judge the 228 + report

- Run `runner.py` over the 228 baseline rollouts with v1, v2, v3 → three new
  `judge_breakdown__*` keys appended to each `results.jsonl`
- Aggregate by model under each composer; diff against the baseline report's
  numbers. Where v1 and v2/v3 disagree, that's the story
- Optional cross-eval: subset (30–50) re-run with `CONCISE_TEACHER` /
  `SOCRATIC_TEACHER` system prompts; show whether explicit anti-firehose
  guidance closes the model-to-model gap
- Write up: either update `baseline_report.md` or land a `baseline_report_v2.md`
  with the hybrid-judged story. Surface in the dashboard's Full Report tab.
- Dashboard: composer-picker on the Results page so viewers can flip between
  v1 / v2 / v3 aggregates (uses the multiple `judge_breakdown__*` fields)

---

## Open questions (decide along the way)

- **Per-criterion weight location**: in the task rubric or in the composer?
  Lean composer-owned (task can still declare overrides via metadata)
- **Return type for deterministic fns**: raw values vs [0, 1] transforms.
  Lean [0, 1] after a per-function calibration, with the raw value logged in
  `terms` for inspection
- **N/A handling**: deterministic functions can return `None` (e.g.
  `code_validity` on a non-code task). Composers renormalize weights, same as
  the current LLM rubric does
- **RL training implications**: v3 is meant to be a fast reward proxy. Think
  through reward-hack surfaces *before* committing to it as a training reward
  (the deterministic functions are harder to fool subtly, but easier to fool
  flagrantly — e.g. saying nothing at all maximizes anti_firehose_length)
