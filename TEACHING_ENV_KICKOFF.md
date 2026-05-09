# Kickoff: LLM Teaching-Quality RL Environment

> Handoff doc for spinning up a new repo. Move this to the new repo's root (or `notes/`) and treat it as a (fallible) guide for "what are we building and why."
> Author of this doc has just finished a sibling project (AurumBench, a B2B-negotiation Verifiers/Prime-Intellect env) — file pointers below where existing patterns are reusable.

---

## 1. What we're building

A Verifiers / Prime-Intellect-compatible RL environment that evaluates how well an LLM **teaches a specific concept** to a specific student, grounded in materials the student is actually using (slides, textbook excerpts, problem sets).

### The task shape (founder's framing, lightly annotated)

A student picks a topic they're learning. For each rollout:

1. **Materials in.** The student supplies the source material they were given in their course — professor's slides, textbook pages, problem sets. (Probably as PDF/markdown/images.)
2. **Model teaches.** The model under test produces a teaching response: text answer + (optionally) generated image/diagram.
3. **Grade it.** Score the teaching response against a rubric for "would this actually teach a student better than they were already being taught" — easier to understand, more concise, deeper understanding, builds bridges to the materials they already have.

The framing differentiator vs every other teaching benchmark: **the model has to teach off-of the student's existing materials**, not give a generic explainer. That forces it to relate, scaffold, and bridge — the things current models are bad at.

### What "good teaching" probably means here

Pulled from prior pedagogy lit + observed model failure modes:

- **Diagnoses before explaining** — what does the student already know / where are they stuck? (Most models skip this entirely.)
- **Scaffolds at the right altitude** — not a firehose, not condescending; matches the student's current frame.
- **Bridges to existing materials** — references what's in their slides/textbook, doesn't ignore or contradict it.
- **Picks the right modality** — when an image actually helps vs adds noise.
- **Builds transferable understanding** — student should be able to handle a slightly different problem after, not just recite back.

---

## 2. Why this is the right bet

### Failure frontier (the pitch line)

> "Here is a failure frontier that SOTA models hit today; here is a (mostly) deterministic way to measure it; here is a path to generate training data against it."

For teaching, all three are true:

- **SOTA fails.** Frontier models firehose, skip diagnosis, ignore the student's actual materials, generate weak diagrams. This is reproducible.
- **Mostly-deterministic measurement.** A simulated-student probe (see §4) gives a non-judge signal. Judge LLM can backstop.
- **Training data path.** Each task = student materials + a held-out probe quiz. You can scale by adding subjects / sources.

### Commercial pull

- AI tutoring is one of the highest-ARR verticals after coding (Khanmigo, Synthesis, Speak, Magic School, Brisk).
- Labs need teaching reward models for RLHF — there is no public benchmark / RL env that gives them this signal today.
- EdTech buyers (universities, K-12) have existing benchmarks they care about (NWEA MAP, formative assessments) — there's a path from "model teaches well" to outcomes those buyers already measure.

### Landscape (what exists, why insufficient)

- **Public teaching benches:** TutorEval, MathDial, Eedi, AI2 pedagogy work, CMU's NaturalLearning. Mostly single-turn, mostly math, mostly graded by static rubrics or judge LLMs.
- **Khanmigo and similar deployments:** real systems but proprietary; their internal evals aren't public.
- **No public RL envs for teaching.** Closest research is "student-model-as-reward" papers (a few from 2024–25), none of which ship as a runnable environment.
- **The hard problem everyone dodges:** the gold-standard reward — "did the student actually learn" — requires longitudinal study or a simulated-student probe. Most public work uses judge LLM and calls it a day; this is the hackable path.

---

## 3. Founder's deliverables checklist

Verbatim from the brief — these are what we ship:

1. **One-page pitch:** what the env measures, why current models fail, why the failure matters commercially.
2. **Runnable repo:** one-command setup, clear README, sample task, sample rollout, sample grader output.
3. **Baseline report:** ≥3 models, 30–100 rollouts total, pass@1 / pass@k or mean reward, failure taxonomy, 2–3 example traces.
4. **Data/rubric card:** what is public vs held-out, what the reward measures, what could be reward-hacked, known caveats.
5. **Demo artifact:** a live dashboard or a short Loom showing the model failing and the grader catching it. (Reference: <https://meeting-intent-dashboard.vercel.app/>.)

The audience is friends at labs and data companies. The pitch isn't "we built an eval" — it's the failure-frontier line above.

---

## 4. The central design decision: what is the reward?

This decision shapes the whole env. Three options:

### (a) Judge LLM grades the teaching response

- **Pro:** cheap, simple, ships fast.
- **Con:** judge LLM is biased toward verbose / confident-sounding answers (the very failure mode we're trying to measure). Reward-hackable.
- **Verdict:** necessary as a backstop / for sub-criteria (e.g., "did it bridge to the materials?"), but should not be the headline reward.

### (b) Simulated-student probe quiz

- The flow: tutor model teaches → simulated student model takes a held-out probe quiz on the concept → reward = student's score (or delta vs a no-tutor baseline).
- **Pro:** deterministic-ish, harder to hack (the model can't bullshit a multiple-choice quiz it's not taking), differentiates this env from every other teaching bench.
- **Con:** adds a second model in the loop; probe-quiz quality becomes its own problem; "student model" choice introduces variance.
- **Verdict:** this is the differentiator. Ship this.

### (c) Both, weighted

- Judge LLM for surface qualities (concision, scaffolding, bridging to materials), student-probe for actual learning gain.
- **Pro:** most informative reward, lets you decompose where models fail.
- **Con:** more moving parts; two reward signals can disagree.
- **Verdict:** likely the right end state, but ship (b) first and add judge later.

### Reward-hacking watch-list (for the rubric card)

- Judge bias toward verbosity → student probe should counterweight
- Tutor "leaks" probe answers verbatim → make probe held-out, paraphrased, or generated post-hoc
- Tutor model and student model are the same → they share priors → use a different (weaker?) student model
- Easy probes → tutor wins by saying anything → calibrate probe difficulty per topic
- Judge inflates scores for confident-sounding answers → use a rubric-bound judge with anchored examples

---

## 5. Prime Intellect / Verifiers — non-obvious gotchas

These cost real hours on the sibling project. Internalize before writing the env.

### Repo layout

```
environments/
  <env_name>/
    pyproject.toml        # uses hatchling, NOT setuptools (see below)
    README.md             # env-level, separate from repo README
    <env_name>/           # the actual Python package
      __init__.py         # exposes load_environment
      env.py              # the MultiTurnEnv subclass
      smoke_test.py       # one-rollout driver
      ... data files ...
```

`prime env push --path environments/<env_name>` builds the wheel **locally** then uploads. Local build must succeed.

### Use hatchling, not setuptools

Prime's CI metadata test asserts `"tags" in pyproject["project"]`. `tags` is **not** a PEP 621 standard field. Setuptools (>= ~v68) strict-validates `[project]` and rejects unknown keys → local build fails. Hatchling does not strict-validate, so `tags` passes through. Use this exact `[build-system]`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "<env-name>"
version = "0.1.0"
description = "..."
requires-python = ">=3.11"
tags = ["teaching", "education", "tool-use", "multi-turn", "agent", "eval", "train", ...]
dependencies = ["verifiers>=0.1.5", "openai>=1.55", "datasets>=2.20"]

[tool.hatch.build.targets.wheel]
packages = ["<package_name>"]
exclude = [
    "<package_name>/runs",
    "<package_name>/runs/**",
    "**/__pycache__",
    "**/*.pyc",
]

[tool.hatch.metadata]
allow-direct-references = true
```

Hatchling auto-includes all files in the package directory (`.md`, `.json`, `.png`, etc.) — no `package-data` config needed. **Do** add `exclude` patterns for runtime caches, scratch dirs, etc.

### Verifiers v0.1.5 API surface

The MultiTurnEnv subclass needs:

- `rollout(client, model, prompt, answer, task, info, **kwargs) -> (completion, state)` — usually keep `super().rollout()` and override only to inject pre-rollout setup (e.g., generating an opening turn from a non-seller actor before the user-under-test sees anything).
- `setup_state(prompt, answer, task, info, state) -> state` — populate state from the dataset row's `info` field. State is per-rollout; don't rely on module globals.
- `env_response(messages, state) -> (Messages, State)` — return the next env-side message(s) plus updated state.
- `is_completed(messages, state) -> bool` — termination condition; check explicit state flags, not message-content heuristics.

The `client` Verifiers passes in is `AsyncOpenAI`. It can point at any OpenAI-compatible endpoint (Prime Inference, vLLM, OpenAI proper, Anthropic shims). **Use it for any internal model calls** (judge, student, etc.) so the env stays portable. Fall back to a separately-configured client only if you specifically need a different endpoint.

### Dataset format gotchas

- Dataset rows have a `prompt` column (list of chat messages) and an `info` column (dict).
- `format_dataset` only prepends `system_prompt` when building from a `question` column. If you pre-build `prompt` as a chat list, **include the system message yourself**.
- `info` field has flat schema across the dataset. If you have variable-schema sub-fields (e.g., per-task assertion lists with different shapes), serialize them as JSON strings and parse at use-time. HuggingFace Datasets will reject mixed schemas otherwise.

### Tool schema format

Verifiers uses Chat Completions tool schemas (nested under `function` key), not Responses-API flat schemas:

```python
{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
```

If you bring in tool defs from elsewhere, convert at module load.

### Wheel verification before pushing

```bash
pip wheel /path/to/env --no-deps -w /tmp/wheel_test
unzip -l /tmp/wheel_test/<env>-0.1.0-py3-none-any.whl  # confirm data files shipped
pip install --force-reinstall /tmp/wheel_test/<env>-0.1.0-py3-none-any.whl
cd /tmp && python -m <package>.smoke_test  # verify no source-tree dependencies
```

`prime env push` will also run a metadata test on Prime's side — `pyproject.toml` must have `name`, `version`, `description`, `tags`, and a non-placeholder description.

### Things the docs don't tell you

- `prime env push` exit-success doesn't mean the metadata test passed. Check the dashboard.
- `prime eval run` requires Prime Inference billing; don't get stuck on this — your smoke test is sufficient for local dev.
- Reverting / unpublishing an env is awkward. The `version` field matters; bump it for breaking changes.

---

## 6. Reusable patterns from AurumBench

Sibling project lives at `~/PolicyRLEnv/environments/aurumdesk_negotiation/`. Don't fork it — copy *patterns*. The negotiation domain code (adversary loop, ZOPA scoring, tool dispatch, policy floors) won't carry over and gutting it is slower than rewriting.

Worth-looking-at files:

- `environments/aurumdesk_negotiation/pyproject.toml` — the hatchling config that survived Prime's metadata test.
- `environments/aurumdesk_negotiation/aurumdesk_negotiation/env.py` — `MultiTurnEnv` subclass shape: `rollout` override, `setup_state`, `env_response`, `is_completed`, dataset construction, single weighted-scalar reward function. The "second actor in the loop" pattern (there it's an adversarial buyer; here it'd be the simulated student) is structurally similar.
- `environments/aurumdesk_negotiation/aurumdesk_negotiation/smoke_test.py` — one-rollout driver. Steal the shape: argparse, async runner, score breakdown print, conversation-tail print.
- `environments/aurumdesk_negotiation/aurumdesk_negotiation/checker/check.py` — multi-assertion grader with weighted partial credit. Useful template for the rubric card.
- `environments/aurumdesk_negotiation/aurumdesk_negotiation/checker/judge.py` — LLM-as-judge integration with caching.
- `environments/aurumdesk_negotiation/README.md` — env-level README structure (what it tests, usage, internals, roadmap).
- `notes/PITCH_ADVERSARIAL_RL_ENVS.md` — the pitch doc that worked. Steal the structure: description / why this / where students are in the loop / verification.
- `notes/AUTHORING_GUIDE.md` — task-authoring guide. The new env will need an analogous one for task contributors (student-material packagers, probe-quiz authors).

What does **not** carry over: adversary loop, ZOPA, tool dispatch, policy enforcement. Skip those entirely.

---

## 7. Open questions to resolve before writing code

Decide these early — most are load-bearing for the env shape:

1. **Subjects.** All STEM? Math only? Programming? Bio? Pick a starter subject (probably 1–2) for v0.1; expand later.
2. **Source material format.** Markdown only (clean, easy)? PDFs (realistic, hard parsing)? Images of slides (realistic, OCR/vision required)? Suggest: markdown-only for v0.1, with a clear path to PDF/image later.
3. **Modality.** Text-only teaching responses for v0.1? Or include image-gen from the start? Suggest: text-only v0.1; image-gen is a v0.2 differentiator.
4. **Single-turn or multi-turn?** Founder's framing reads single-turn ("the student shows the model the materials, asks a question, the model answers"). Multi-turn (tutor-student dialog) is more realistic but harder to grade. Suggest: single-turn v0.1; multi-turn dialog is v0.2.
5. **Probe quiz design.** MCQ (deterministic grading)? Free-response (judge-graded)? Mixed? How many questions per topic? Held-out from the tutor or visible? Suggest: 3–5 MCQ + 1 free-response per topic, **held-out** from tutor.
6. **Student model choice.** GPT-5.4-mini? A weaker model (so probe results are floor-bounded)? Multiple, ensembled? Suggest: weak-but-honest student model (gpt-4.1-nano-equivalent) for v0.1.
7. **Topics / dataset size.** How many topics for v0.1? Suggest: 10–20 hand-authored topics across 1–2 subjects, then proceduralize.
8. **Public vs held-out split.** Critical for the data card. v0.1 likely all public (small enough that this is fine); v0.2 has held-out probe sets.

Don't try to answer all eight in one shot. (1), (4), (5), and (6) are the structural ones.

---

## 8. User preferences (from prior project memory)

- **Default cheap-but-smart model:** gpt-5.4-mini for judges, drafting, analysis. **Do not** use it for the agent under test or for slots where capability stratification matters (e.g., baselines across model tiers).
- **Schema simplicity:** for documentation content (rubrics, task cards), prefer concrete examples + prose notes over rigid structured fields. Reserve structure for what the harness actually consumes.
- **Underserved domains:** prioritize hard-to-verify tasks where public benches are absent or saturated. (Teaching-with-student-materials qualifies.)
- **Prompt writing:** when writing prompts for AI agents (judges, students, tutors), inhabit the role — think about what info the model would actually need to play it well.

---

## 9. Suggested first moves in the new repo

Order roughly:

1. **Decide §7 (1), (4), (5), (6).** Don't write code until these are pinned.
2. **Build a single end-to-end task by hand** — one topic, one set of materials, one probe quiz, one tutor response, one grader output. Run it through manually. Confirm the reward signal does what you want.
3. **Wrap that single task in a Verifiers env** — copy the AurumBench plumbing patterns. Smoke test should run a full rollout (tutor → student probe → grade) end-to-end.
4. **Push to Prime Intellect** as v0.1.0 with one task. Don't wait for the full dataset; the PI envelope is what's risky, not the content.
5. **Author 10–20 tasks**, run baselines on 3 models (e.g., gpt-5.5, gpt-5.4-mini, gpt-4.1-nano), build the failure taxonomy from the traces.
6. **Write the pitch / data card / demo artifact.**

Total time-to-shippable-v0.1 is probably 2–3 weeks if §7 is decided cleanly.

---

## 10. The pitch test

Before shipping anything, the env should pass this test:

> Show a friend at a lab a sample tutor response that scored low, the materials it was teaching off-of, the probe quiz the student failed, and ask: "is this measuring something real that current models are bad at, that you'd want to RL against?"

If the answer is yes, ship. If it's "I don't know, this could be judge-LLM noise," go back to §4 and tighten the reward.
