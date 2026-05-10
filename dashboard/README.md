# TeachingBench dashboard

Single-page web dashboard for browsing TeachingBench tasks, viewing saved rollouts, and triggering fresh ones live.

## Architecture

```
                         Cloudflare Pages                     Hugging Face Spaces (Docker)
                              (static)                                  (Python)
                       ┌────────────────────┐               ┌────────────────────────────┐
                       │  Next.js 15 App    │               │  FastAPI                   │
   browser ─── HTTPS ──┤  Tailwind v4       ├── HTTPS/SSE ──┤  /api/tasks                │
                       │  app/page.tsx      │               │  /api/runs                 │
                       │                    │               │  /api/runs/{id}            │
                       └────────────────────┘               │  /api/run (SSE)            │
                                                            │                            │
                                                            │  ↓ imports                 │
                                                            │  teachingbench.evaluate()  │
                                                            └────────────────────────────┘
                                                                       │
                                                                       ▼
                                                                    OpenAI API
```

The split is forced: Cloudflare Pages can't run Python (its functions are JS/TS only), so the FastAPI service lives on a free HF Space and the static frontend talks to it.

## Layout

- **`backend/`** — FastAPI app (`app.py`), Dockerfile for HF Spaces, `requirements.txt`, README.
- **`frontend/`** — Next.js 15 (App Router) + Tailwind v4 + TypeScript. Static export → Cloudflare Pages.

## Quick start (local)

Two terminals:

```bash
# terminal 1 — backend
cd dashboard/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../../environments/teachingbench
export OPENAI_API_KEY=sk-...
uvicorn app:app --reload --port 8000
```

```bash
# terminal 2 — frontend
cd dashboard/frontend
cp .env.example .env.local      # NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
npm install
npm run dev                      # → http://localhost:3000
```

Open `http://localhost:3000`. You should see the two sample tasks, your saved rollouts (from the smoke-test runs), and a working "Run fresh rollout" button.

## Deployment

See:
- `backend/README.md` — HF Spaces (Docker SDK, free CPU tier).
- `frontend/README.md` — Cloudflare Pages (Next.js Static HTML Export).

Order of operations: deploy backend first, copy its URL, set `NEXT_PUBLIC_BACKEND_URL` on Cloudflare, deploy frontend, then add the Cloudflare URL to the HF Space's `ALLOWED_ORIGINS` secret.

## v0.1 limitations

- **Streaming is faked.** `verifiers.evaluate` is monolithic — backend runs the rollout to completion then replays messages with a small delay. Real per-turn streaming needs a `MultiTurnEnv.add_trajectory_step` hook. v0.2.
- **No auth.** Server-side OpenAI key, no per-user rate limit. Acceptable for low-balance accounts and low-traffic demo URLs; add per-IP rate limiting before wider sharing.
- **No model picker in the UI.** Defaults are read from backend env vars (`DEFAULT_TUTOR_MODEL`, etc.). Add a model dropdown when we want to compare.
- **No live progress for long rollouts.** The "Running…" state hangs until the rollout completes; only then does the transcript replay. Tighten with the v0.2 streaming hook.
