# concept_explanation

Tasks where the student asks the tutor to explain a concept at a stated level
(e.g. "what is X?", "why does Y work?"). The workhorse teaching shape — see
`/TEACHING_USE_PATTERNS.md` §1 for the framing.

Layout: `concept_explanation/<subject>/<topic_slug>/meta.yaml`.

Defaults for this category:

- **No `materials/` directory.** The student is asking from their head, not
  pasting a doc. (If your task involves the student handing the tutor a
  document, it probably belongs in a different category — `decoding/` or
  `feedback_as_teaching/`.)
- **`bridging` will score `null`** under the default rubric — that's correct.
  No materials = no bridging to test.
- **Rubric pressure is on `clarity` + `audience_pitch` + `anti_firehose`.**
  The default failure mode is the model dumping a textbook chapter at the
  wrong level.
- **Turns: 3–5** typical. Concept-explanation conversations naturally
  involve a follow-up clarification or two.
