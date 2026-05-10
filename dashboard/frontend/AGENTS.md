# AGENTS.md — read this before editing the frontend

> If you're an AI agent (or a human) about to change `dashboard/frontend/`, **read this file first**. It captures non-obvious design choices and decisions made over multiple sessions that aren't recoverable from the code alone.

## What this is

A single-page Next.js 15 app for the TeachingBench dashboard. Two halves — left = task selector + rubric + saved-runs list, right = chat transcript + score panel. Static-exported (`output: "export"` in `next.config.ts`) so it deploys to Cloudflare Pages with no JS runtime needed on the host.

The backend is a separate FastAPI service on Hugging Face Spaces. See `../backend/`. Frontend talks to backend over HTTPS + SSE.

## Architecture choices

- **Single client component (`app/page.tsx`).** All state lives at the top of `Page()`. Components are inline functions in the same file. **Don't split into separate component files until the file exceeds ~600 lines** — premature componentization makes state-passing fiddlier than it's worth here. (User-stated preference: keep things readable in one place.)
- **Tailwind v4, no `tailwind.config.ts`.** Theme tokens live in `app/globals.css` as CSS custom properties under `@theme { ... }`. To add a color, edit the `@theme` block; don't reach for `tailwind.config.ts`.
- **No shadcn/ui yet.** Plain Tailwind classes. shadcn was considered and skipped to keep the dep tree small. Pull it in if/when we need a non-trivial component (Dialog, Combobox, etc.) — until then resist.
- **CSS custom properties for colors**, accessed via `var(--color-foo)` directly (NOT through Tailwind theme syntax). This is intentional — Tailwind v4's theme bridge is awkward for arbitrary properties, and inline `style={{ background: var(...) }}` works for the dynamic anchor-row tints below.

## Markdown rendering

- `react-markdown` + `remark-gfm` (GFM = tables, strikethrough, autolinks, task lists).
- Wrapped in a `<div className="md-content">` whose styles live in `globals.css` under `.md-content`. **Don't add markdown styles globally** — scope them to `.md-content` so they don't leak into the rubric panel or chrome.
- Both **chat messages** AND the **judge rationale** are rendered as markdown. If you add a new place that displays model-generated text, wrap it in the `<Markdown content=... />` component too.
- Code fences inside markdown render as `<pre><code>...</code></pre>`. The `pre` element gets dark-mode styling from `globals.css` (top-level `pre` rule); the inline `code` and code-inside-pre get scoped overrides under `.md-content`.

## Run-completion handling (DO NOT regress)

The user explicitly reported (May 2026) that the UI was getting stuck on "Running rollout…" and they had to manually click into the saved-runs list to see the result. We have **two complementary completion paths** — both must keep working:

1. **SSE `done` event.** Backend's `/api/run` streams an `event: done` message after the rollout completes. The page handles this in the `streamRun` for-await loop (`if (evt.type === "done") { ... }`).
2. **Polling fallback** (`useEffect` in `Page()` that depends on `mode`). While `mode === "running"`, polls `api.listRuns()` every 3 seconds and looks for a run ID that wasn't there when the user pressed "Run fresh." If a new run appears, calls `loadSavedRun(newRunId)`. This catches the case where SSE didn't make it through (proxy buffering, parse hiccup, etc.).
3. **`status` state** — also shows the user *where* we are during the long wait between "request sent" and "messages start streaming." Without this, the UI feels frozen for 15–60 seconds.

If you refactor the run-fresh flow, **keep both completion paths**. Removing the polling fallback will reintroduce the original bug.

## SSE parser quirks

In `lib/api.ts`, `streamRun()` is a hand-rolled SSE parser (we use `fetch()` + `ReadableStream`, not `EventSource`, so we can use `POST` with a JSON body). Critical details:

- **CRLF normalization.** `decoder.decode(...).replace(/\r\n/g, "\n")` — some proxies emit CRLF line endings, and the parser only scans for `\n\n` separators. **Don't remove this.** Without it, the SSE events will accumulate in the buffer and never be yielded — exactly the original "stuck on Running…" symptom.
- The parser ignores lines that aren't `event:` or `data:`. sse-starlette emits keep-alive `: ping` comment lines; we skip them silently.
- Multi-line `data:` is concatenated with `\n` before JSON.parse.

## Rubric layout

- Each criterion is its own card with a border, in `<RubricView>`. **Don't collapse them back into a flat list** — the user explicitly asked for separation between criteria.
- Anchors render as a stacked rows table inside each card, sorted **null first, then numeric descending**. Rationale: `null` means "N/A" (criterion doesn't apply), so it's qualitatively different from "scored 0" and visually goes at the top so it's not mistaken for a low score.
- Anchor rows have a faint colored background tint based on score (green for ≥0.75, amber for ≥0.4, red below, gray for null). This was specifically requested for readability. Tints are very subtle (~0.10 alpha) — if you make them stronger, double-check contrast on the dim text colors.
- The score column in the anchor row is a fixed-width monospace cell on the left. Keep the width consistent across criteria.

## Saved runs list

- Format: timestamp on top-left, score badge top-right, then `task_id — Teacher: <model>` underneath.
- The "Teacher:" prefix matters — without it the model name reads as a generic label. The user requested this explicitly.
- Sorting is newest-first (the backend returns it that way; trust it, don't re-sort on the client).

## Color & status conventions

| Variable | Use |
|---|---|
| `--color-bg` | page background |
| `--color-panel` | task / rubric card backgrounds |
| `--color-panel-hover` | hover state for clickable rows |
| `--color-border` | all dividers and card borders |
| `--color-text` | primary text |
| `--color-text-dim` | secondary / metadata text (timestamps, captions, criterion descriptions) |
| `--color-accent` | call-to-action (button, links, the active selection border) |
| `--color-good` | score ≥ 0.75 (green) |
| `--color-warn` | score ≥ 0.4 (amber) |
| `--color-bad` | score < 0.4 (red) |

The score-band thresholds (`>= 0.75`, `>= 0.4`) appear in **two places** — `ScoreBadge` and `anchorRowBg`/`anchorScoreText`. Keep them in sync.

## Backend coupling

- `lib/types.ts` mirrors the FastAPI response shapes. If you change a backend endpoint's JSON, update `types.ts`.
- `BACKEND_URL` is read from `NEXT_PUBLIC_BACKEND_URL`. For local dev, falls back to `http://localhost:8000`.
- The frontend assumes the backend's `/api/run` endpoint streams `info` / `message` / `done` / `error` events. The polling fallback assumes that on completion a new run appears in `/api/runs` — this requires the backend to save results before yielding `done`. (Currently it does, via the `evaluate(save_results=True, ...)` config in the env.)

## Things explicitly NOT done (yet)

- **No model picker in the UI.** The backend uses env-var defaults. Adding a dropdown is fine, but currently most rollouts are debugging the env, not comparing models.
- **No per-message live streaming during the rollout.** `verifiers.evaluate` is monolithic — we only get the transcript after it's done. The backend replays it message-by-message with a 50ms delay so it *feels* live. Real per-turn streaming needs a `MultiTurnEnv.add_trajectory_step` hook.
- **No auth.** Server-side OpenAI key. If the demo URL ever gets shared widely, add per-IP rate limiting.

## When you change something here

- **Update this file.** If you're adding a new component, new endpoint hook, or new state shape, document why. The point of this file is that future-you (or another agent) can edit safely without re-deriving the design.
- **Don't break the polling fallback.** Worth saying twice.
- **Test the long-wait UX.** Click "Run fresh" and confirm the status text updates from "Starting…" → "Running rollout…" → (eventual) "Streaming transcript…" → final scores. Silence for 30 seconds is a regression.
