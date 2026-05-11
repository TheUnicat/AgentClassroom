# Round 1 findings (2026-05-11)

First baseline pass. 4 tutors × 57 tasks × 1 trial = 228 rollouts, judged by Opus 4.7 with the v3 rubric. Numbers below are *uncertainty-free* (n=1 per cell) — treat as directional, not statistically rigorous. Round 2 will give error bars.

## Headline

| Tutor | Mean composite | rank |
|---|---|---|
| **claude-opus-4-7** | **0.635** | 1 (tied) |
| **gpt-5.4-nano** | **0.635** | 1 (tied) |
| gpt-5.4-mini | 0.618 | 3 |
| gpt-5.4 | 0.596 | 4 |

The most expensive (Opus) and cheapest (nano) tutors are **tied for best**. The most capable OpenAI model (gpt-5.4) is **worst**. Spread across the lineup is only **0.039** — much smaller than within-tutor task variance (~0.7 range per tutor). **Capability isn't the binding constraint on teaching quality at the current frontier.**

## Where the differences come from (per-criterion means)

| Criterion | nano | mini | gpt-5.4 | opus |
|---|---|---|---|---|
| answers_the_question | 0.89 | 0.92 | 0.93 | **0.95** |
| factual_correctness | 0.91 | 0.94 | **0.96** | 0.93 |
| bridging | 0.68 | 0.67 | 0.65 | **0.76** |
| **anti_firehose** | **0.29** | 0.22 | **0.15** | 0.27 |
| meeting_student_level | 0.78 | 0.81 | 0.77 | **0.85** |
| scaffolding | 0.55 | 0.53 | 0.47 | **0.58** |
| clarity | 0.87 | 0.88 | 0.88 | **0.90** |
| **no_excessive_validation** | 0.70 | **0.87** | **0.90** | **0.60** ← |

Two big effects driving the rankings:

1. **gpt-5.4 firehoses hardest** (anti_firehose=0.15). Loses on the criterion with the strongest ceiling. Every other criterion gpt-5.4 either ties or wins; the firehose ceiling alone drops its composite by ~0.04.

2. **Opus is sycophantic** (no_excessive_validation=0.60, ~0.30 lower than gpt-5.4). "Totally fair", "Great question", "What a thoughtful observation" — Opus opens with empty validation often. The 0.85 ceiling on this criterion costs Opus ~0.06. Without this, Opus would clearly be #1.

3. **Opus is best at bridging materials** (0.76 vs 0.65-0.68 for others). Worth flagging because the eval intentionally tests materials engagement. Opus reads the PDFs in a way that shows.

## Materials boost teaching quality across the board

| Tutor | text-only (n=42) | materials (n=15) | Δ |
|---|---|---|---|
| gpt-5.4-nano | 0.625 | 0.664 | +0.038 |
| gpt-5.4-mini | 0.613 | 0.629 | +0.016 |
| gpt-5.4 | 0.577 | 0.649 | +0.072 |
| claude-opus-4-7 | 0.622 | 0.674 | +0.052 |

**Every tutor scores HIGHER on materials tasks.** Counterintuitive — these are advanced (Spivak, lecture notes, SVD work, problem sets) and should be harder. The mechanism is what we hypothesized in the inter-task variance check: **having a PDF to reference forces shorter, more focused responses** (less firehose). Materials act as a structural anti-firehose lever. The effect is largest on gpt-5.4 (+0.072), which is consistent with that being the most firehose-prone tutor.

## Most and least discriminative tasks

**Widest inter-tutor spread (most discriminative)** — top 5:

| Task | Spread | nano / mini / 5.4 / opus |
|---|---|---|
| cs/postgres_syntax_error | 0.60 | 0.96 / 0.96 / 0.91 / **0.36** |
| math/orthonormal_notes_cut_off | 0.43 | 0.48 / 0.83 / 0.68 / 0.91 |
| math/spivak_cs_major_for_ml | 0.32 | 0.54 / 0.57 / 0.55 / 0.86 |
| math/svd_did_i_do_this_right | 0.32 | 0.64 / 0.53 / 0.61 / 0.85 |
| cs/python_script_slow | 0.31 | 0.61 / 0.30 / 0.50 / 0.58 |

**Tightest spread (least discriminative)**:

| Task | Spread | nano / mini / 5.4 / opus |
|---|---|---|
| math/orthonormal_notes_blank_explain_from_scratch | 0.015 | 0.55 / 0.57 / 0.55 / 0.57 |
| cs/big_o_notation | 0.031 | 0.55 / 0.55 / 0.55 / 0.58 |
| math/linear_independence_vs_orthogonality | 0.042 | 0.68 / 0.68 / 0.72 / 0.68 |

The tight-spread tasks are interesting — they pin all 4 tutors to roughly the same score, often because firehose is the binding constraint and all 4 trip the same ceiling. These probably need different rubric pressure (or different framing) to discriminate models well.

## One anomaly worth telling

**cs/postgres_syntax_error**: Opus scored **0.36** while everyone else got 0.91+. Why?

Looking at the rationale: Opus actually thought deeper than the prompt rewards. The task is a missing-comma SQL error. The other tutors gave the clean answer ("you need a comma between signup_date and country"). Opus started down the same path, then second-guessed itself — *"actually `country` would be parsed as an alias, then FROM is fine — so the real reason this errors is..."* — and the explanation muddled. Judge correctly anchored factual_correctness at 0.3 ("misleading without strictly lying") and clarity at 0.5.

This is **capability hurting teaching quality**. Opus's deeper analysis confused the student. Worth noting as a single data point — the pattern probably reverses on harder tasks where Opus's depth pays off.

## Implementation notes for future judging passes

1. **Opus 4.7 has a tool-call format quirk**: ~17% of calls emit XML-style `<parameter name="...">val` tags inside the JSON tool input, leaking criteria values to the top level. We hit 38/228 affected. Recoverable from batch response; permanently fixable by flattening the input_schema. See `feedback_opus_xml_tool_input.md` memory.

2. **Opus temperature deprecated**: drop the param. See `feedback_opus_temperature_deprecated.md`.

3. **Caching works as designed**: per-call cache reads = 6,456 tokens (rubric + tool schema), non-cached = ~3,200 tokens (transcript + topic). Effective cost of Opus 4.7 as judge on 228 calls batched: ~$5 (vs ~$8 without caching).

4. **Wall-clock**: 228-call batch ended in 7 minutes. Way faster than 24h SLA.

## What to do next

- **Round 2 (n=2 per cell)**: gives us actual error bars. Costs ~$15-18. ~30 min wall-clock. The 0.039 spread across tutors is currently within plausible noise (we measured ±0.014 inter-rollout floor on the SAME task earlier), so round 2 is needed before claiming the ranking is real.
- **Sycophancy criterion calibration**: Opus drops 0.06 on the composite because of no_excessive_validation. Worth double-checking whether the anchors are too aggressive against Opus's friendly style, or whether Opus is genuinely sycophantic-er than the OpenAI tutors. Sample some rationales.
- **Add a less-capable tutor**: gpt-3.5-class would test the "weak teacher can teach well" thesis. If it scores ~0.5-0.6, it confirms the framing.
- **Tightest-spread tasks need a look**: are they just "anti_firehose pins everyone" tasks, or genuinely uninformative? Decide whether to redesign or drop.

## Cost reconciliation (round 1)

| Component | Estimated | Notes |
|---|---|---|
| nano + mini real-time rollouts | ~$1.50 | real-time, all 114 cells |
| gpt-5.4 batched rollouts | ~$5 | 5 turn-batches with auto-caching |
| opus batched rollouts (text + materials) | ~$5-6 | 2 phases × ~5 turn-batches |
| opus batched judging | ~$5 | 228 calls in one batch with explicit caching |
| **Total** | **~$17-18** | |

Under the $20-budget threshold I was worried about. Round 2 doubles the rollout cost but judging won't scale linearly (cache hits more).
