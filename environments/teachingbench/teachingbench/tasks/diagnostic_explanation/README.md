# diagnostic_explanation

Tasks where the student has hit a problem (broken code, error, failed deploy,
slow query, "my X isn't working") and wants the tutor to figure out what's
wrong. See `/TEACHING_USE_PATTERNS.md` §2 for the framing.

Layout: `diagnostic_explanation/<subject>/<topic_slug>/meta.yaml`.

## Design choices for this category

- **Mix of with-paste / without-paste tasks.** Pastes (code, config,
  traceback, query) are inlined directly into `seed_question`. No-paste
  tasks open with a deliberately terse seed ("my python script is slow")
  to simulate the very common case of a user who doesn't yet know what
  info to provide.
- **Difficulty skews introductory–intermediate.** Real CS pastes tend to
  be embarrassingly easy for anyone with experience — the rubric pressure
  is on *how* the tutor diagnoses + teaches, not whether they get the
  answer.
- **Student prompts are detailed and include ground truth.** Each per-task
  student prompt specifies (a) what facts the user has access to and would
  share if asked, (b) what the user doesn't know and would ask about, and
  (c) the *actual* underlying bug + correct fix + plausible-but-wrong
  fixes the user should reject. This lets the student LLM react accurately
  to suggestions ("yes that worked" / "I tried that, didn't help") without
  volunteering the answer up front.
- **Remedial-education paths.** For technical terms the persona doesn't
  know (e.g. "what's a Dockerfile?", "what's `cProfile`?"), the student
  asks rather than fabricates. After the tutor explains, the student
  provides the requested info.
- **Rubric pressure.** `bridging` will score on tasks with a paste (does
  the tutor reference what the student gave?), `null` on most no-paste
  tasks. `anti_firehose` is heavily exercised — the failure mode is
  listing 5 possible causes instead of converging. `scaffolding` is
  exercised when the right move is to ask a question rather than dump a
  fix.
- **Turns: 3–5.** Higher end (4–5) for terse seeds where the tutor has to
  drive multiple rounds of question-asking. Lower (2–3) for paste-and-fix
  cases.
