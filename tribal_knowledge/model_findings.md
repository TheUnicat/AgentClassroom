# Model-comparison findings (n=1, sanity-check scale)

Single-rollout sketches comparing tutor models on the v3 rubric. Not baseline-quality (no n>1, no error bars), but already produced load-bearing observations worth keeping.

## Headline: capability isn't the binding constraint on teaching quality

Across two tasks compared three ways (gpt-5.4-nano, gpt-5.4-mini, gpt-5.4 all as tutors, with gpt-5.4-mini student + gpt-5.4 judge + v3 tightened rubric):

| Task | nano | mini | gpt-5.4 | Best |
|---|---|---|---|---|
| `cs/halting_problem` (text-only, advanced) | **0.641** | 0.477 | 0.609 | nano |
| `math/spivak_x_i_exponent_or_index` (materials, intro) | 0.915 | **0.955** | 0.927 | mini |

The most capable model (gpt-5.4) is *not* the best tutor under our rubric on either task. The "best tutor" varies by what's binding the composite.

## Why the most capable model loses ground

GPT-5.4 firehoses more than mini, which firehoses more than nano. Same task, judges' rationales independently flag this:

- gpt-5.4 on halting_problem: *"nearly every tutor turn is long, sectioned, and contains multiple analogies, nuances, and optional extensions… Gödel, Rice, semi-decidable side references that were not necessary for this student's immediate confusion."*
- gpt-5.4 on spivak: anti_firehose=0.72 vs mini's 0.90. Same task, gpt-5.4 still adds "notation survival guide" extras.

More capable → more content available to share → more verbose by default → punished by anti_firehose. The rubric specifically rewards "what the student needs, no more," which cuts against the natural tendency of bigger models to be comprehensive.

## When mini bombs: edge of competence

On halting_problem (advanced topic), mini's `factual_correctness` dropped to **0.45** — judge caught real technical errors. Nano and gpt-5.4 both held at 0.95. So:

- **Mini ≈ best on tasks within its competence.** Conversational length, no firehose, factual fine.
- **Mini collapses at edge of competence.** Verbosity isn't the binding issue anymore — *being wrong* is. Factual hits the floor.
- **Nano can win on hard topics not by being smarter but by being too small to over-elaborate.** It gave a shorter, correct exposition on halting_problem. Doesn't always work — depends on whether nano has the knowledge at all.

## Materials tasks tighten the spread

The materials task spread was 0.04 across three tutors (0.915-0.955); the text-only halting task spread was 0.16 (0.477-0.641). Possible reasons:
- Short turn count (2 vs 4) → less opportunity to accumulate firehose-y messages
- Having a PDF to reference forces tighter, more focused responses (we noted this earlier — the binding ceiling on spivak was scaffolding, not anti_firehose, suggesting the PDF "pulls" the tutor toward concrete reference rather than free-form elaboration)
- Simple question (notation) is well within all three models' competence → no factual collapse

Worth checking on harder materials tasks (e.g. `spivak_polarization_from_property_4` or `math/svd_ta_marked_wrong`) to see if the spread reopens.

## Implications for TeachingBench's thesis

This eval IS measuring teaching quality, not raw capability — that's the whole point. The early data supports the thesis:

- A weaker model (gpt-5.4-nano) can beat a stronger one (gpt-5.4) at teaching when the task is within both models' competence.
- The cost-of-additional-capability is paid in firehose, not bought in clarity.
- At the edge of competence, capability matters again — but that's a separate failure mode (factual errors), distinct from teaching quality.

**A defensible takeaway for the founder pitch**: TeachingBench isn't a capability benchmark — it's a *teaching-presentation* benchmark, and the data so far shows that even GPT-3.5-class models would likely do well *if* they had the right presentation discipline. Worth running gpt-3.5 (or claude-3-haiku, gemini-flash, etc.) as tutor to validate this claim concretely before pitching.

## What to test next to firm this up

- **n=4-8 rollouts per model per task** to get error bars. Single rollouts have ±0.060 uncertainty (intra-judge at temp 0.7); model gaps need to be larger than that to be meaningful.
- **A weaker model (gpt-3.5-turbo, claude-haiku, gemini-flash)** as tutor on the same two tasks. If it scores 0.6-0.9 — comparable to gpt-5.4 — the "capability isn't binding" thesis lands hard.
- **A harder materials task** to see if the tight spread on spivak is a topic-difficulty artifact or a real materials effect.

## When to redo

- After adding new tasks of significantly different difficulty
- After any rubric retuning that changes which criterion is binding
- Before publishing baseline numbers (need n>1 by then)
- If a new headline finding contradicts these (e.g. mini suddenly beats nano on hard topics)
