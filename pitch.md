# AgentClassroom

*See `baseline_report.md` for the long version.*

**Capability ≠ teaching.**

Capability benchmarks (used to) crown GPT-5.4. This teaching eval shows it loses to GPT-5.4-nano.

Models know the material. They've read all the textbooks. So when teaching, they open with "Great question!", write a textbook chapter about the topic that covers everything the student could possibly want to learn up to grad school, and end with "want me to cover W, X, Y, Z next?" 

Students bounce. 

## What we built

- 57 Math and CS teaching tasks; 15 with uploaded reference materials (textbook pages, lecture notes, handwritten homework)
- LLM-LLM rollouts. LLM teacher, simulated student, and a judge.
- An 8-criterion rubric that penalizes common LLM teaching failure patterns. The equation for the overall score captures non-linear relationships and is tunable after judging.
- Tested 4 models from multiple providers (OpenAI + Anthropic) for a total of 228 rollouts. 
- Modular. Drop in your model. Drop in your rubric.

## Results (n=228, full dataset)

*Table 1: Criterion and composite scores by model (mean across 57 tasks); Student simulated by GPT-5.4-mini in all trials*

| Criterion | GPT-5.4-nano | GPT-5.4-mini | GPT-5.4 | **Opus 4.7** |
|---|---|---|---|---|
| Answers the question | 0.89 | 0.92 | 0.93 | **0.95** |
| Factual correctness | 0.91 | 0.94 | **0.96** | 0.93 |
| Engages with materials | 0.68 | 0.67 | 0.65 | **0.76** |
| No firehosing | **0.29** | 0.22 | **0.15** ← | 0.27 |
| Matches student's level | 0.78 | 0.81 | 0.77 | **0.85** |
| Scaffolds | 0.55 | 0.53 | 0.47 | **0.58** |
| Clarity | 0.87 | 0.88 | 0.88 | **0.90** |
| No sycophancy | 0.70 | 0.87 | 0.90 | **0.60** ← |
| **Composite** | **0.635** | 0.618 | 0.596 | **0.635** |
| Cost per rollout | ~$0.005 | ~$0.015 | ~$0.10 | ~$0.22 |

The cheapest and most expensive models are tied.

Individual criteria tell a different story: 0.14 gap between best and worst on firehosing (GPT-5.4 vs GPT-5.4-nano), and 0.30 on sycophancy (Opus 4.7 vs GPT-5.4) — both statistically significant. The eval rewards teaching, not raw capability.

## Failure modes

**All models dump too much information.** Average firehose score across all models is 0.23. The best (GPT-5.4-nano) tops out at 0.29. GPT-5.4 is the worst at 0.15: on `halting_problem` it answered one conceptual question with five long sections and an unsolicited "want me to also cover Rice's theorem?" invitation. I would like to note that the pattern is systemic and has been around since GPT-3.5.

**Opus 4.7 would be clearly the best teacher if not for sycophancy.** ~30% of Opus 4.7 replies open with "Great question!", "Totally fair", "What a thoughtful observation." Score on sycophancy: **0.60** (worst in corpus). Without the criterion, Opus 4.7 would be unambiguously first.

**Capability can reduce performance.** On a missing-comma SQL syntax error, Opus 4.7 identified the fix correctly, then second-guessed its own explanation mid-sentence: *"actually, the real parse issue is..."* and never recovered, achieving an overall score of **0.36** on a task where all cheaper models scored 0.91+. Capability can be bad for simple tasks.

## The signal is real

- Same transcript, judge replayed 5 times: composite CV **0.003**.
- Same task, full rollout repeated 5 times: composite CV **0.010**.
- Different tasks, same tutor: composite range **0.48 to 0.96** (the eval discriminates).
- Different judge models: tutor ranking holds; absolute scores shift. Smaller judges saturate. We use Opus 4.7.

## Caveats

LLM-simulated students aren't real students and miss the messy way real users phrase things even with our prompting. Real students would give a cleaner signal and verify the benchmark. Potential improvements with real students: 

- **Auto-generated quizzes** at the end of each rollout to measure what students actually learned. 
- **Student self-rating**. Ask real users to rate clarity / confusion / usefulness of conversations
- **LLM judging of actual conversation transcripts too**

## Market

AgentClassroom is one of the only benchmarks built for teaching quality. Potential markets for Deep24:

**AI tutoring companies** (Khan's Khanmigo, Synthesis, MagicSchool, Numerade). They pick a model and Deep24 tells them GPT-5.4-mini gives ~97% of Opus 4.7's teaching quality at 7% the cost. 

**Frontier labs doing RLHF on teaching.** They need a teaching reward signal and human ratings are slow and expensive. Single-turn teaching benchmarks that focus on factual accuracy measure nothing useful.

## Teaching is low-hanging fruit

Models already know the material. Content criteria — *answering the question* and *factual correctness* — are nearly saturated across the lineup. 

The problem is presentation, especially avoiding firehosing and sycophancy. These are *not* capability problems. A targeted RL pass against this rubric can flip them in a single training run. AgentClassroom makes that training possible.

## Notes
- I didn't implement image generation because it's expensive and rarely helpful. Code execution and making graphs may be more helpful, but this will require human students

## TODOs
- RL training loop. fine-tune a weak base model to teach well.


