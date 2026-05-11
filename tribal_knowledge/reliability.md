# Reliability — what we know about judge & pipeline variance

Where to look when you're trying to decide whether a baseline gap is real or noise. Numbers from 2026-05-10 testing on the v3 composite (`v3-convex-revquad-ceilings` in `grader/reward_scoring.py`).

## Five kinds of variance, defined

These overlap in intuition but measure different things. Don't mix them up.

| Kind | What it asks | "Higher is..." | Script |
|---|---|---|---|
| **Intra-judge replay** | Same input, multiple judge calls — how much does the judge wobble? | bad (noise floor) | `judge_reliability_check.py --n N` |
| **Inter-judge** | Same input, different judge models — do they agree? | bad (capability gap or rubric ambiguity) | `judge_reliability_check.py --n 1 --judge-model X` |
| **Inter-temperature** | Same judge, different temperatures — does temp 0.2 hide borderline cases? | informative (reveals borderline criteria) | `judge_reliability_check.py --temperature T` |
| **Inter-rollout** | Same task run end-to-end multiple times — student + tutor + judge all freshly generated | bad (pipeline noise) | `task_reliability_check.py --n N` |
| **Inter-task** | One rollout each across N *different* tasks — does the eval discriminate? | **good** (eval is responsive to task differences) | `inter_task_check.py --task-ids ...` |

## What we measured (2026-05-10, big_o_notation rollout)

### Intra-judge replay (n=8, same saved transcript)

| Rubric | Judge | Temp | Composite mean | Composite CV |
|---|---|---|---|---|
| v1 (additive, 4 criteria) | nano | 0.2 | 0.881 | 0.039 |
| v3 (conv+ceil, 8 criteria) | nano | 0.2 | 0.881 | 0.007 |
| v3 + tightening | gpt-5.4 | 0.2 | 0.631 | 0.024 |
| v3 + tightening | gpt-5.4 | 0.7 | 0.636 | 0.047 |

**Takeaway**: the ceiling mechanism in v3 dampens composite variance dramatically. Per-criterion CV can be higher (good — judge is using the middle of the score range), but the composite is clipped by the lowest-scoring criterion's ceiling, which is itself stable. v3 noise floor is tighter than v1 even with twice as many criteria.

### Inter-judge (n=1 each, same transcript, v3 tightened rubric, temp 0.2)

| Judge | Composite | anti_firehose | no_excessive_validation |
|---|---|---|---|
| nano | 0.913 | 0.800 | 0.800 |
| mini | 0.833 | 0.500 | 1.000 |
| gpt-5.4 | **0.609** | **0.200** | 0.700 |

**Takeaway**: judge capability dominates judge sampling. Same transcript, same rubric, same temperature — gpt-5.4 gives composite 0.30 lower than nano. Nano saturated 6/8 criteria at endpoints (didn't really read the rubric); gpt-5.4 actually applied the anchors. **No amount of rubric tightening fixes this — upgrade the judge.**

The 1.5× composite gap is not noise — it's the right answer (the rollout had wall-of-text + listicle messages averaging ~400 words per turn, which is exactly the `anti_firehose ≤ 0.3` anchor). Nano didn't see it; gpt-5.4 did.

### Inter-temperature (n=8, gpt-5.4, v3 tightened, big_o)

| Temp | Composite mean | CV | Range |
|---|---|---|---|
| 0.2 | 0.631 | 0.024 | 0.609–0.641 |
| 0.7 | 0.636 | 0.047 | 0.609–0.679 |

**Takeaway**: the mean is stable across temperatures — **no hidden systematic bias at low temperature**. Temperature controls the *range* of plausible judgments, not the *centre*. Use temp 0.2 for production eval (tighter noise floor); use temp 0.7 to surface which criteria have genuine borderline-call uncertainty.

In our case, `anti_firehose` and `no_excessive_validation` are the wobbliest at higher temp. The composite stays stable because the ceiling mechanism dominates.

### Inter-rollout (n=5 full rollouts, `cs/big_o_notation`, gpt-5.4-mini tutor + student, gpt-5.4 judge, v3 tightened, temp 0.2)

Per-trial composites: **0.598, 0.609, 0.598, 0.598, 0.609**

| Level | Range | Mean | CV |
|---|---|---|---|
| Composite | 0.598–0.609 | 0.603 | **0.010** |
| Per-criterion `scaffolding` | 0.62–0.90 | 0.708 | 0.162 |
| Per-criterion `no_excessive_validation` | 0.70–1.00 | 0.854 | 0.134 |
| Per-criterion `factual_correctness` | 0.72–0.90 | 0.812 | 0.111 |
| Per-criterion `anti_firehose` | 0.18–0.20 | 0.188 | 0.058 |

**Counterintuitive but important: composite inter-rollout CV (0.010) is *tighter* than composite intra-judge replay CV (0.024 at temp 0.2).** Why? Because gpt-5.4-mini *reliably* firehoses this task — anti_firehose pins at 0.18-0.20 across every fresh rollout. That criterion's ceiling binds the composite, and the binding criterion is stable across the 5 rollouts. The per-criterion churn on scaffolding (0.62-0.90, CV 0.162) and no_excessive_validation (0.70-1.00, CV 0.134) is masked by the ceiling clipping the composite below those criteria's contributions.

**Takeaway**: inter-rollout composite stability is driven by *which criterion is binding the ceiling*. If the binding criterion is stable across runs (tutor's consistent failure mode), composite is stable. If the binding criterion *changes* across runs, composite variance jumps. The per-criterion noise tells you what's load-bearing on the underlying judgment; the composite tells you the headline number.

### Inter-task (n=5 distinct tasks, gpt-5.4-mini tutor + student, gpt-5.4 judge, v3 tightened, temp 0.2)

| Task | Composite | Binding ceiling |
|---|---|---|
| `cs/halting_problem` | 0.477 | anti_firehose @ 0.565 |
| `math/derivative_what_it_measures` | 0.679 | anti_firehose @ 0.679 |
| `cs/git_committed_to_main` | 0.721 | anti_firehose @ 0.721 |
| `cs/python_keyerror_dict` | 0.865 | anti_firehose @ 0.884 |
| `math/spivak_x_i_exponent_or_index` | 0.955 | scaffolding @ 0.981 |

Mean 0.739, stdev 0.184, **CV 0.249**, range **0.478**.

**Takeaway**: the eval *does* discriminate between tasks. Composite spread is large (~0.5) and meaningful — harder topics + tasks more likely to trigger firehose score lower. Most tasks are bound by `anti_firehose` because gpt-5.4-mini consistently has firehose tendencies; the *severity* of firehose differs by task (which is what produces the spread). The materials task was bound by `scaffolding` instead — apparently having a PDF to reference forces more focused, less firehose-y answers. Worth re-checking on more materials tasks.

For inter-task variance, a *high* CV is good news (the eval is responsive). A very low cross-task CV would warn that the rubric / ceilings are pinning everything to the same number regardless of actual task difficulty.

## Practical noise floors (v3 + gpt-5.4 judge, recommended config)

- **Intra-judge at temp 0.2**: ±0.030 (2σ). Use for baseline comparison precision when scoring the *same* transcript multiple times.
- **Intra-judge at temp 0.7**: ±0.060. Use for "could this borderline call have gone the other way?"
- **Inter-rollout (full pipeline)**: ±0.012 (2σ) *for a task where the binding ceiling criterion is stable*. Can be much larger if the binding criterion churns across rollouts — re-measure per-task if unsure.
- **Inter-task SPREAD (signal, not noise)**: ~0.5 range across 5 diverse tasks (gpt-5.4-mini tutor). Per-task scores 0.48–0.96. Higher is better — confirms the eval discriminates rather than pinning everything to the same number.
- **Combined eval precision**: Δreward > ~0.03 for confident relative ranking when ceiling stability holds. > ~0.07 for robust ranking that handles borderline judge calls AND ceiling churn.

## What's *not* noise

- Inter-judge gap of 1.5× composite (nano vs gpt-5.4): capability problem. Use gpt-5.4.
- Per-criterion CV > 0 on `anti_firehose` / `no_excessive_validation` at temp 0.7: genuine borderline-call uncertainty on conversational micro-judgments. Won't reduce by lowering temperature alone.
- Composite drop from 0.91 → 0.61 between nano and gpt-5.4: the rubric is being applied correctly under gpt-5.4. The 0.91 was wrong.

## Mistakes to avoid

- **Treating low-temp judge determinism as "high reliability."** Nano scored identical numbers on 6/8 criteria across 8 replays — looked great, was actually saturating without reading. Always cross-check with inter-judge comparison before declaring reliability.
- **Equal-weighting variance sources.** Pipeline (inter-rollout) variance is usually larger than judge replay variance. If you're tightening reliability, start with the pipeline (fixed seeds, stable student persona, lower tutor temperature) before fussing with judge replay.
- **Quoting noise floors without temperature.** "CV=0.024" without "@ temp 0.2" is ambiguous — temperature dominates the wobble at the criterion level. Always specify.
- **Reading composite variance without per-criterion variance.** The ceiling mechanism *hides* per-criterion noise inside a stable composite. If you ever want to diagnose what's noisy, look at the per-criterion stdev, not just the composite.
- **Assuming inter-rollout variance > intra-judge variance.** We measured the opposite — inter-rollout CV=0.010 vs intra-judge CV=0.024 on the same task — because the ceiling clamps the composite at a stable criterion's bound. Don't generalize from this one task; the ordering flips if the binding criterion isn't stable across rollouts.

## How to re-measure

```bash
# Intra-judge replay (cheap, ~$0.05–0.10 for n=8 on gpt-5.4):
python -m teachingbench.judge_reliability_check <run_id> --n 8 --judge-model gpt-5.4 --temperature 0.2 --use-current-rubric

# Inter-judge sweep (~$0.02 total for n=1 each):
for m in gpt-5.4-nano gpt-5.4-mini gpt-5.4; do
  python -m teachingbench.judge_reliability_check <run_id> --n 1 --judge-model $m --use-current-rubric
done

# Inter-temperature (n=8 at each temp, ~$0.20):
python -m teachingbench.judge_reliability_check <run_id> --n 8 --temperature 0.2 --use-current-rubric
python -m teachingbench.judge_reliability_check <run_id> --n 8 --temperature 0.7 --use-current-rubric

# Inter-rollout (n=5 full rollouts of one task, ~$0.50–1.00 depending on materials):
python -m teachingbench.task_reliability_check --task-id <id> --tutor-model gpt-5.4-mini --student-model gpt-5.4-mini --judge-model gpt-5.4 --n 5

# Inter-task (n distinct tasks, one rollout each, ~$0.05–0.10 per task):
python -m teachingbench.inter_task_check \
  --task-ids cs/big_o_notation math/derivative_what_it_measures \
             cs/halting_problem cs/python_keyerror_dict \
             math/spivak_x_i_exponent_or_index \
  --tutor-model gpt-5.4-mini --judge-model gpt-5.4
```

## When to redo this

- After any rubric structure change (weights, anchors, ceiling shapes)
- After a judge or tutor model swap
- After a new category (e.g. multimodal materials tasks) lands in baselines
- If composite distributions in saved rollouts look off (saturating at 1.0 or 0.0 unexpectedly across many tasks)
- Before publishing any baseline numbers — at least intra-judge + one inter-rollout check on a representative task

