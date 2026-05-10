
# How people actually use LLMs for teaching/explanation

Working reference for TeachingBench task authoring. **Distilled from OpenAI/NBER
"How People Use ChatGPT" (2025), Anthropic Economic Index reports (Jan + Mar
2026), Pew (Jun 2025), and Anthropic's educator + university-student reports.**
Sources at the bottom.

The categories below are the ones that **(a) appear high in real usage data**
and **(b) translate cleanly into a `{topic, audience, materials, seed_question}`
TeachingBench task**. This is a task-authoring tool, not an exhaustive taxonomy.

## Framing fact

**~73% of ChatGPT use is non-work / personal** (OpenAI/NBER, n≈1.5M
conversations). The default mental model — "a student doing homework" — is the
*minority case*, but it's what we're doing here. Most teaching-shaped requests come from adults handling their own life: their lab results, their lease, their tax form, their hobby project,
their job's new tool. 

---

## 1. Concept explanation ("explain X")

Single-shot or multi-turn explanation of a concept, calibrated to a stated
level. The workhorse teaching shape — appears in nearly every LLM usage study
as the top "Practical Guidance" subuse.

- **Example request**: *"Can you explain what a database index is? I write SQL
  for work but never really understood why some queries are slow."*
- **TeachingBench pressure**: clarity, answering at an appropriate complexity for the audience, anti-firehose (one very common failure mode is dumping a textbook chapter).

## 2. Diagnostic explanation (errors, debug, "what does this mean")

User pastes/describes a failing artifact (error message, broken code, weird
test result, unexpected output) and wants the LLM to *explain* what's wrong
and why. This is the dominant CS-tutoring shape and a heavy chunk of OpenAI's
"Technical Help" bucket.

- **Example request**: *"I'm getting `KeyError: 'user_id'` on line 14 — here's
  the function. Why is this happening?"*
- **TeachingBench pressure**: bridging from materials (the pasted artifact),
  scaffolding (don't just hand back the fix; explain the diagnosis).

## 3. Worked examples on the user's own data

User supplies their actual numbers/inputs and wants the LLM to walk through
the calculation or transformation step by step. Common in finance, stats,
DIY measurement, fitness/nutrition, cooking, science homework.

- **Example request**: *"I make $4,200/mo, want to save for a house in 5
  years, and have $8k saved already. Walk me through how much I need to put
  away monthly at 4% APY."*
- **TeachingBench pressure**: bridging (uses *their* numbers, not generic
  ones), step-by-step clarity, anti-firehose (don't lecture about compound
  interest theory first — answer the question).

## 4. Decoding professional content

**User-flagged category.** Non-experts trying to understand documents that
were written by/for professionals: lab results, contracts, lease clauses,
tax forms (W-2, 1099, Schedule C), insurance EOBs, legal notices, paper
abstracts, prescription inserts. Volume is large and growing per Pew (US
adults using AI for "learning" went 8% → 26% from 2023 to 2025) and is
underrepresented in academic-flavored teaching benchmarks.

- **Example request**: *"My lease has a clause that says 'Tenant shall be
  liable for two months' rent as liquidated damages upon early termination,
  except where statutorily prohibited.' What does this actually mean for me
  if I move out 3 months early?"*
- **Example request**: *"Here are my CBC results — neutrophils are flagged
  high at 8.2, lymphocytes flagged low at 1.1. What does this combination
  usually indicate? I have a doctor's appointment on Thursday."*
- **TeachingBench pressure**: heavy on **anti-firehose** (the failure mode is
  reciting every line item in the document), heavy on **bridging** (must
  reference *their* clause / *their* values), and on appropriate hedging
  (medical/legal — explain without overpromising).

## 5. Cross-domain expert pitching

**User-flagged category.** The user is an expert in field A reading content
from field B. Neither ELI5 nor full jargon is right — the LLM has to *use*
the user's known field to bridge. Documented in Anthropic's educator report
(faculty self-report ~29% of AI time on their own learning, often outside
their specialty) and is a known sharp edge for default LLM behavior, which
tends to over-simplify when it shouldn't.

- **Example request**: *"I'm an MD reading a paper on transformer attention
  in radiology. Can you explain what a 'key/query/value' is, assuming I know
  linear algebra and some signal processing but nothing about NLP?"*
- **Example request**: *"I'm a 20-year backend engineer trying to understand
  why my React state isn't updating."'* (Implicit: Don't explain JavaScript fundamentals
  to me, just the model.)
- **TeachingBench pressure**: heaviest on **audience pitch** — wrong-level
  responses are the modal failure. Tests whether the model can *use* what
  the user already knows instead of restarting from zero.

## 6. Feedback-as-teaching (critique their draft/code/argument)

**User-flagged category.** User submits *their own* artifact (essay, code,
proof, business plan, cover letter, lesson plan) and asks for critique that
*teaches them why*. OpenAI reports ~2/3 of "Writing" usage is *modifying
user-supplied text* — this is the dominant Writing-cluster shape, not
de-novo generation. Very common in ESL/EFL learning per Springer 2024 review.

- **Example request**: *"Here's my cover letter for a data analyst role.
  What's weak about it, and why?"*
- **Example request**: *"I wrote `for i in range(len(arr)): if arr[i] in
  seen: return True; seen.add(arr[i])`. My instructor said it's O(n²) but
  I don't see why. Can you walk me through it?"*
- **TeachingBench pressure**: scaffolding (correct without humiliating),
  bridging (must reference *their* specific text), and anti-firehose
  (don't rewrite everything — flag the load-bearing issues).

## 7. Misconception repair

User states a belief that's wrong (or partially wrong) and wants the LLM to
correct/clarify. Often signaled by phrasing like *"I think it works like X,
is that right?"* or *"isn't it true that..."*. High value for the rubric
because the failure mode (sycophancy or letting it slide) is well-documented.

- **Example request**: *"For recursion, I think the base case is just for
  efficiency — the function would still work without it, just slower, right?"*
- **Example request**: *"I always heard that you should drink 8 glasses of
  water a day. Is the science actually solid on that?"*
- **TeachingBench pressure**: scaffolding (correct kindly + explain *why*
  the misconception is intuitive), anti-sycophancy.

## 8. Briefing / prep ("get me ready for X")

User has an upcoming event (meeting, interview, exam, doctor visit, deposition,
parent–teacher conference) and wants compressed targeted prep, not a
textbook. Strongly time-bounded; high-stakes phrasing common.

- **Example request**: *"I have a stand-up tomorrow on the OAuth migration
  and I haven't touched auth before. What are the 3 things I most need to
  understand by tomorrow morning?"*
- **Example request**: *"I'm seeing my oncologist tomorrow about a recent
  biopsy. What questions should I be ready to ask, and what answers should
  I be prepared to hear?"*
- **TeachingBench pressure**: anti-firehose (must prioritize ruthlessly),
  audience pitch, scaffolding (acknowledge what the user can absorb in the
  available time).

---

## Notes for task authoring

- A good v0.1 task set should hit **all four rubric criteria under different
  conditions**, not just stress one criterion many ways. Map each new task
  to which category above it instantiates and which criteria it pressures.
- Tasks WITH materials test bridging directly. Tasks WHERE THE MATERIALS ARE
  NOISY OR LONG test bridging *and* anti-firehose.
- "Cross-domain expert" tasks are the cheapest way to test
  audience-pitching, because the right answer is neither ELI5 nor jargon —
  the model has to actively use the stated background.
- "Decoding professional content" is the biggest underrepresented archetype
  in academic teaching benchmarks. Adding 1–2 of these (lab result, lease
  clause, tax line) likely gives more discriminative signal than another
  intro-coding task.

## Sources

- [OpenAI/NBER: How People Use ChatGPT (Chatterji et al., w34255)](https://www.nber.org/papers/w34255)
- [OpenAI: How people are using ChatGPT (blog)](https://openai.com/index/how-people-are-using-chatgpt/)
- [Anthropic Economic Index: Learning curves (Mar 2026)](https://www.anthropic.com/research/economic-index-march-2026-report)
- [Anthropic Economic Index: Economic primitives (Jan 2026)](https://www.anthropic.com/research/anthropic-economic-index-january-2026-report)
- [Anthropic education report: How educators use Claude](https://www.anthropic.com/news/anthropic-education-report-how-educators-use-claude)
- [Anthropic education report: How university students use Claude](https://www.anthropic.com/news/anthropic-education-report-how-university-students-use-claude)
- [Pew: 34% of US adults have used ChatGPT (Jun 2025)](https://www.pewresearch.org/short-reads/2025/06/25/34-of-us-adults-have-used-chatgpt-about-double-the-share-in-2023/)
- [Springer: ChatGPT in ESL/EFL — systematic review (2024)](https://link.springer.com/article/10.1186/s40561-024-00342-5)
- [a16z: Where Enterprises are Actually Adopting AI](https://a16z.com/where-enterprises-are-actually-adopting-ai/)
