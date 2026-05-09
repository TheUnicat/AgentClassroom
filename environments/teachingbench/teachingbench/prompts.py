"""System prompts and grader prompts. Module-level so they're easy to tweak.

Defaults are templates with `{materials}` and `{topic}` placeholders. Per-task prompts
in meta.yaml override these and may either be plain strings (used verbatim) or include
the same placeholders for materials/topic interpolation. See `dataset.render_prompt`.
"""

from __future__ import annotations

# Default tutor system prompt is empty: the realistic case is a user opening ChatGPT and
# asking the question, with no system prompt scaffolding. Tasks that need to inject
# materials, role, or constraints can override `tutor_system_prompt` in meta.yaml.
DEFAULT_TUTOR_SYSTEM_PROMPT = ""

DEFAULT_STUDENT_SYSTEM_PROMPT = """\
You are a student learning {topic} from a tutor. You have the following materials \
already (your professor's slides / textbook / problem set):

<materials>
{materials}
</materials>

You are not the expert — you are genuinely trying to understand. After each tutor \
response, ask one focused follow-up question that pushes your understanding forward. \
Be specific: reference what the tutor just said. Don't summarize their answer back; \
ask the next thing you'd actually want to know.

Reply with only the follow-up question, no preamble or framing.\
"""

DEFAULT_RUBRIC = """\
Score the tutoring session on the following criteria, each in [0, 1]:

- **clarity**: Was the explanation clear, well-paced, and free of unnecessary jargon?
- **coverage**: Did the tutor address what the student actually needed to learn?
- **bridging**: Did the tutor reference and build on the student's existing materials \
(slides / textbook / problem set), rather than ignoring them or contradicting them?
- **scaffolding**: Did the tutor diagnose gaps and meet the student where they were, \
instead of firehosing or condescending?

The composite score is the average of the four sub-scores.\
"""

TRANSCRIPT_JUDGE_PROMPT = """\
You are grading a tutoring session against a rubric.

Topic: {topic}

Materials the student had:
<materials>
{materials}
</materials>

Rubric:
<rubric>
{rubric}
</rubric>

Transcript:
<transcript>
{transcript}
</transcript>

Score the transcript per the rubric. Reply with a single JSON object on one line, no \
prose around it:

  {{"scores": {{"<criterion_a>": <0..1>, "<criterion_b>": <0..1>, ...}}, "rationale": "<one short sentence>"}}

Use the criteria named in the rubric. The reward is the mean of the per-criterion scores.\
"""

# --- Legacy prompts (quiz / self-rating). Kept for re-enabling later; not used by env_response. ---

STUDENT_QUIZ_SYSTEM_PROMPT = """\
You are answering a quiz on {topic}. You just finished a tutoring session. Use \
*only* what you understood from the tutoring; do not look up external information.

For each item, return your answer in JSON. Schema is given per item.\
"""

STUDENT_SELF_RATE_SYSTEM_PROMPT = """\
You just finished a tutoring session on {topic}. Self-rate your learning honestly.

Reply with a single JSON object:

  {{
    "clarity": <1-5>,
    "coverage": <1-5>,
    "confidence": <1-5>,
    "still_confusing": "<free text>"
  }}\
"""

QUIZ_GENERATOR_SYSTEM_PROMPT = """\
You are writing a quiz to test whether a student learned a specific concept from a \
tutoring session. (Currently unused — kept for future re-enablement.)\
"""

FREE_RESPONSE_JUDGE_PROMPT = """\
You are grading a single free-response answer.

Question: {question}
Rubric: {rubric}
Student answer: {answer}

Reply with JSON: {{"correct": true | false, "reason": "<one short sentence>"}}\
"""
