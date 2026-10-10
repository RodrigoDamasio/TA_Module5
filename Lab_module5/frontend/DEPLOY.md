# Frontend deployment (Vercel)

Live: **https://taller-research-agents.vercel.app** · Vercel project `taller-research-agents` (scope `rodrigodamasiojulio-9268`), deployed 2026-10-10. API: https://backend-production-13ec.up.railway.app ([backend/DEPLOY.md](../backend/DEPLOY.md)).

## Steps run

```bash
# 0. the backend first: /health must expose `limits` (the UI's schema requires them)
cd TA_Module5/Lab_module5/backend && railway up --detach --service backend --environment production

# 1. Vercel (CLI installed under Node 18's global bin)
export PATH=/home/rodrigo/.nvm/versions/node/v18.18.2/bin:$PATH
cd ../frontend
vercel link --yes --project taller-research-agents
printf 'https://backend-production-13ec.up.railway.app' | vercel env add NEXT_PUBLIC_API_URL production
vercel --prod --yes                     # → aliased to https://taller-research-agents.vercel.app

# 2. CORS on Railway (redeploys the API)
cd ../backend
railway variables --set "FRONTEND_ORIGIN=http://localhost:3000,https://taller-research-agents.vercel.app"
```

- `NEXT_PUBLIC_API_URL` is inlined at **build** time: changing it needs `vercel env rm/add` and a new `vercel --prod`.
- Vercel holds no secret; the Gemini key stays on Railway.
- **First deploy failed** ("Failed to type check"): `next build` type-checked `tests/`, whose fixtures import the real sample runs from `../backend/samples/`, and Vercel uploads only `frontend/`. Fix: `typescript.tsconfigPath: "tsconfig.build.json"` in `next.config.ts`; that file excludes `tests/` and `e2e/`. `npm run typecheck` still checks everything.

## Post-deploy checks (2026-10-10)

| Check | Result |
|---|---|
| Page public | 200 |
| Bundle contains the Railway URL | Found in `/_next/static/immutable/chunks/…js` |
| CORS from the Vercel origin | Preflight `POST /run`, a 404 problem response and the **SSE stream** (`text/event-stream`) all carry `access-control-allow-origin: https://taller-research-agents.vercel.app` |
| E4 — each sample replays its stored run, no POST request | Pass |
| E6 + E7 — 375 px: no horizontal scroll, tabs, axe clean | Pass |
| E8 — one real run with approval → approve → answer with sources, axe clean at the approval step | Pass in 5.5 s · **0 real Gemini calls, 8 cached** (same task and settings as the backend's post-deploy check X5) |

```bash
BASE_URL=https://taller-research-agents.vercel.app npm run test:e2e   # 3 passed, 4 local-only skipped
```

## Redeploy

```bash
npm run typecheck && npm run lint && npm run test && npm run test:e2e   # gates
vercel --prod --yes
```
