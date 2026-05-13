# gradingbench

A Verifiers / Prime-Intellect RL environment that evaluates how well an LLM **grades student work** against a rubric, compared to a ground-truth human teacher grade. Sibling package to `teachingbench`.

## Status

v0.1 — **structure only, awaiting real data**. The package scaffolds the env, dataset loader, prompts, and reward function. The shipped `gradingbench/data/synthetic.jsonl` contains 5 hand-crafted placeholder examples; replace them with human-graded data before running real evals.

## Concept

Each rollout is single-turn:
1. The grader model under test is shown a student's work + a rubric (a `vf.SingleTurnEnv`).
2. It returns a structured JSON object `{"grade": <int in [1,4]>, "rationale": "<short text>"}` via response_format (OpenAI) or forced tool use (Anthropic).
3. Reward = how closely the predicted grade matches the ground-truth human grade:
   `reward = 1 - |pred - actual| / 3`
   (exact match = 1.0, off by 1 = 0.67, off by 2 = 0.33, off by 3 = 0.0)
4. A secondary `exact_match` metric (0 or 1) is logged for diagnostic plotting.

## Local development

```bash
cd environments/gradingbench
pip install -e .

python -c "from gradingbench.env import load_environment; env = load_environment(); print('env:', type(env).__name__, 'rows:', len(env.dataset))"
```

## Configuration via `load_environment`

```python
load_environment(
    num_examples=None,             # cap dataset to first N rows
    judge_model="gpt-5.4-nano",    # model used by the agreement metric machinery
    judge_client=None,             # AsyncOpenAI; default constructs from env vars
    **kwargs,                      # forwarded to vf.SingleTurnEnv
)
```

Note: in single-turn outcome scoring the "judge" is just the reward function reading
the grader's structured output and comparing to the ground truth — no extra LLM call
is required at scoring time. The provider-aware dispatch (`_call_grader_openai`,
`_call_grader_anthropic`) exists for the optional grader rollout path and to keep
the file shape sibling-consistent with `teachingbench/grader/judge.py`.

## Dataset schema

Each row in `gradingbench/data/synthetic.jsonl`:

```python
{
    "task_id": "essay-001",
    "subject": "english",                    # english | math | cs | history | ...
    "prompt": "Grade the following student response to ...",
    "student_work": "<the student's actual answer>",
    "rubric": [
        {"label": "thesis clarity", "anchors": [...]},
        ...
    ],
    "ground_truth_grade": 3,                 # int in [1,4]
    "ground_truth_rationale": "<optional, may be empty>",
    "grader_id": "teacher_a",                # for inter-rater study later
}
```

## Grading scale (1-4 ordinal)

- 1 = poor
- 2 = needs improvement
- 3 = satisfactory
- 4 = excellent

Simple integer, easy to match against human grade, supports continuous reward via the formula above.

## Package layout

```
gradingbench/
├── env.py                       # GradingEnv (vf.SingleTurnEnv) + load_environment
├── prompts.py                   # DEFAULT_GRADER_SYSTEM_PROMPT, GRADING_USER_PROMPT_TEMPLATE
├── dataset.py                   # load_dataset() + _validate_row helper
├── grader/agreement.py          # GradingRubric — agreement_score reward + exact_match metric
└── data/synthetic.jsonl         # placeholder 5 examples (TODO: replace with real data)
```

## TODO before live use

- Replace `data/synthetic.jsonl` with human-graded examples covering the target subjects.
- Add an inter-rater reliability check script once we have multiple `grader_id`s per task.
- Wire structured-output sampling args into the env's `sampling_args` so the rollout itself
  enforces the JSON schema (currently the reward function parses whatever the model emits).
