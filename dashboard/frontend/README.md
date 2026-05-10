# Dashboard frontend (Next.js 15)

Single-page Next.js app for browsing TeachingBench tasks, viewing saved rollouts, and triggering fresh ones. Static-exported (`output: "export"`) so it deploys cleanly to Cloudflare Pages.

## Layout

```
+--------------------------+--------------------------+
|  TASK selector           |                          |
|    + seed question       |                          |
|    + Run fresh button    |   CHAT / transcript      |
|--------------------------+   (saved or live)        |
|  RUBRIC view             |                          |
|    (criteria, anchors,   |                          |
|     score badges)        |                          |
|--------------------------+--------------------------|
|  SAVED RUNS list         |   SCORE PANEL            |
|    (click to load)       |   (composite + per-      |
|                          |    criterion + rationale)|
+--------------------------+--------------------------+
```

## Local dev

```bash
cd dashboard/frontend
cp .env.example .env.local        # edit if backend isn't on :8000
npm install
npm run dev                        # → http://localhost:3000
```

The backend must be running first (see `../backend/README.md`).

## Build for production

```bash
npm run build
# → produces ./out/ as a fully static site
npx serve out                      # optional: preview locally
```

## Deploy to Cloudflare Pages

1. Push `dashboard/frontend/` to a git repo (or use the same repo as the backend, just point Cloudflare at the frontend directory).
2. On dash.cloudflare.com → Workers & Pages → Create → Pages → Connect to Git.
3. Build settings:
   - **Framework preset:** Next.js (Static HTML Export)
   - **Build command:** `npm run build`
   - **Build output directory:** `out`
   - **Root directory:** `dashboard/frontend` (if the repo is the whole TeachingBench)
4. Environment variables (Production + Preview):
   - `NEXT_PUBLIC_BACKEND_URL` = `https://<your-username>-<space-name>.hf.space` (your HF Space URL)
5. Deploy. Cloudflare gives you a `*.pages.dev` URL.

> **Don't forget:** add the Cloudflare URL to the backend's `ALLOWED_ORIGINS` env var on the HF Space, otherwise CORS will block the requests.

## Files

- `app/page.tsx` — the entire UI lives here as a single client component (kept as one file intentionally; split when it grows).
- `app/layout.tsx`, `app/globals.css` — chrome + dark theme via Tailwind v4 `@theme` block.
- `lib/api.ts` — typed backend client + `streamRun` async generator that parses SSE.
- `lib/types.ts` — shared types matching backend JSON.
- `next.config.ts` — `output: "export"` for static deploy.
