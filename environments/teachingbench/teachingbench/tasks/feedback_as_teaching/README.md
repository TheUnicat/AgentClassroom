# feedback_as_teaching

Tasks where the student submits *their own* artifact (essay, code, proof,
homework solution, cover letter) and asks for critique that *teaches them
why*. See `/TEACHING_USE_PATTERNS.md` §6 for the framing — OpenAI reports
~2/3 of "Writing" usage is modifying user-supplied text, making this the
dominant Writing-cluster shape (not de-novo generation).

Layout: `feedback_as_teaching/<subject>/<topic_slug>/meta.yaml`.

## Design choices for this category

- **The artifact comes from the user.** Their handwritten work, their code,
  their draft. Usually lives in `materials/` as a PDF / image / pasted text.
- **Tutor must reference *their* specific artifact.** Generic feedback that
  could apply to any submission is the failure mode. Strong `bridging`
  pressure.
- **Scaffolding is the headline criterion.** Correcting without humiliating
  + explaining *why* the error is intuitive matters more than getting the
  technical answer right. Tutors that just dump a corrected version score
  poorly even when their answer is correct.
- **Anti-firehose pressure too**: don't rewrite the whole thing — flag the
  load-bearing issues. "Here are 8 things wrong" is worse than "here's the
  one thing that's wrong + why".
- **Turns: 3–4** typical. Critique → student asks a follow-up → tutor
  clarifies. Sometimes the student first wants to know IF it's wrong; the
  tutor's job is to help them find the error themselves rather than
  reveal it directly.
