# Dashboard backend (FastAPI)

A small FastAPI app that exposes TeachingBench tasks, saved rollouts, and a fresh-rollout endpoint to the dashboard frontend.

## Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health probe + config introspection |
| `GET` | `/api/tasks` | Tasks with rubric + metadata |
| `GET` | `/api/runs` | Saved rollouts (summary, newest first) |
| `GET` | `/api/runs/{id}` | One saved rollout in full |
| `POST` | `/api/run` | Trigger fresh rollout. SSE stream. |

### `POST /api/run` body

```json
{
  "task_id": "cs/intro_python_hello_world",
  "tutor_model": "gpt-5.4-nano",
  "student_model": "gpt-5.4-mini",
  "judge_model": "gpt-5.4-nano"
}
```

Models default to the env-var-driven defaults (`DEFAULT_TUTOR_MODEL`, etc.). The SSE stream emits:
- `event: info` — `{status, ...}` checkpoints
- `event: message` — `{role, content}` per transcript message
- `event: done` — `{reward, judge_breakdown, stop_condition, metrics}`
- `event: error` — `{error}`

## Local development

```bash
cd dashboard/backend
python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt
pip install -e ../../environments/teachingbench

export OPENAI_API_KEY=sk-...
uvicorn app:app --reload --port 8000
```

Then `curl http://localhost:8000/api/health` should return `status: ok`.

## Configuration (env vars)

| Var | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | (required) | OpenAI key — server-side, no per-user auth |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Override for OpenAI-compatible endpoints |
| `TEACHINGBENCH_RUNS_DIR` | `<repo>/environments/teachingbench/outputs/runs` | Where to read/write saved rollouts |
| `DEFAULT_TUTOR_MODEL` | `gpt-5.4-nano` | |
| `DEFAULT_STUDENT_MODEL` | `gpt-5.4-mini` | |
| `DEFAULT_JUDGE_MODEL` | `gpt-5.4-nano` | |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins. Set to your Cloudflare Pages URL in prod. |
| `LOG_LEVEL` | `INFO` | |

## Deploy to Hugging Face Spaces

1. Create a new Space on huggingface.co. SDK: **Docker**. Hardware: **CPU basic (free)**.
2. Connect the Space to a GitHub repo OR push directly. The Space build will use this `Dockerfile`. Make sure the Dockerfile build context is the **repo root**, not `dashboard/backend/` — it needs to `COPY environments/teachingbench/`.
   - If your Space is its own repo (separate from the main one), copy `dashboard/backend/Dockerfile`, `dashboard/backend/app.py`, `dashboard/backend/requirements.txt`, and the `environments/teachingbench/` directory into the Space repo, preserving the relative paths the Dockerfile expects.
3. Add Space secrets:
   - `OPENAI_API_KEY` — your OpenAI key.
   - `ALLOWED_ORIGINS` — your Cloudflare Pages URL (e.g. `https://teachingbench.pages.dev`).
4. The Space will build and expose port 7860; HF wraps it at `https://<your-username>-<space-name>.hf.space/`.
5. Test: `curl https://<...>.hf.space/api/health` should return `status: ok` with `openai_key_set: true`.

### Persistent runs dir on HF Spaces

The Dockerfile sets `TEACHINGBENCH_RUNS_DIR=/data/runs`. To make this survive Space restarts, enable **persistent storage** on the Space (Settings → Variables and secrets → Persistent storage, free tier supports a small disk). Alternatively, leave runs ephemeral — they'll be lost on Space restart but reappear when fresh rollouts are run.

## v0.1 caveats

- **Streaming is faked.** `verifiers.evaluate` is monolithic; we run the rollout to completion, then replay the transcript message-by-message with a small delay. A real per-turn streaming hook is a v0.2 enhancement (would require subclassing `MultiTurnEnv.add_trajectory_step` to emit events).
- **Rollouts are not concurrent-safe** at the Space level — HF free CPU has 1–2 workers, simultaneous rollouts will queue.
- **No rate limiting.** If the URL gets shared widely, OpenAI bill grows. Add per-IP rate limiting before going viral.
