# Backend deployment (Railway)

Live: **https://backend-production-13ec.up.railway.app** · project `taller-research-agents`, service `backend`, deployed 2026-10-10.

## Steps run

The free Railway plan allows 2 projects. The Module 3 project (`taller-migration-agent`) was deleted first, by the owner's decision; Module 4 (`taller-codebase-rag`) stays live.

```bash
railway delete --project taller-migration-agent --yes --json      # accepted; listed until removal

cd TA_Module5/Lab_module5/backend
railway init --name taller-research-agents --workspace <workspace-id>
railway add --service backend --variables "DATABASE_PATH=/data/research.db"
railway service link backend
railway volume add --mount-path /data
railway domain --json                     # → https://backend-production-13ec.up.railway.app
railway variables --set "BASE_URL=https://backend-production-13ec.up.railway.app" \
  --set "GEMINI_MODEL=gemini-3.5-flash-lite" \
  --set "RATE_LIMIT_RUNS_PER_MINUTE=3" --set "RATE_LIMIT_RUNS_PER_DAY=15" \
  --set "FRONTEND_ORIGIN=http://localhost:3000" --skip-deploys

# run by the owner (the key is never printed):
grep '^GOOGLE_API_KEY=' ../../../.env | cut -d= -f2- | tr -d '\n' \
  | railway variable set GOOGLE_API_KEY --stdin --skip-deploys > /dev/null

pytest -q && ruff check .                 # gate: 87 passed
railway up --detach --service backend --environment production
```

- The key was verified by comparing **SHA-256 fingerprints** of the Railway value and `.env` (match); variables are listed by name only.
- The first `railway variable set` attempt failed with a local **DNS error** (`backboard.railway.com` not resolvable); nothing was sent. The retry worked.
- `PROMPT_SECRET` is not set: the app generates one at first start and keeps it in the volume's database, so nonces, the canary and the response cache survive restarts.
- Build + start took about **60 s**; Railway's health check uses `/health` (`railway.json`).
- **Single replica**: the run queue, the rate limiter and SQLite are in-process. Do not scale horizontally.

## Post-deploy checks (2026-10-10)

| # | Check | Result | Calls |
|---|---|---|---|
| X1 | `/health`: `service_level: full`, `llm_mode: gemini`, `wikipedia: live`, prompt v2 · `/agents`: 5 agents · `/stats` | Pass | 0 |
| X2 | `/samples`: the 3 exported runs; `/samples/rag-vs-finetuning`: completed, `sample: true` | Pass | 0 |
| X3 | Bad JSON → 400 `malformed-request`; short task → 422; 2,100 chars → 413 `input-too-large`; `max_iterations: 9` → 422; unknown run → 404 `run-not-found` (all `application/problem+json`) | Pass | 0 |
| X4 | SSE through Railway's proxy: events arrived **live** over 30 s (not buffered); two `agent_started` at the same moment (Reviewer + Fact-Checker in parallel) | Pass | — |
| X5 | Real run "When should I use RAG instead of fine-tuning?", approval on: paused at `awaiting_approval` (draft + expiry) → approve → `completed`; 4 decisions (researcher → writer → reviewer + fact_checker → FINAL); sources *Retrieval-augmented generation*, *Fine-tuning (deep learning)*, *Vector database*; 55 s; est. $0.0028 at paid prices; a second approve → 409 `invalid-transition` | Pass | 8 |
| X6 | CORS from `http://localhost:3000` on preflight and on a 404 problem; an unknown origin gets no `allow-origin` | Pass | 0 |
| X7 | Logs: run ids, sizes, counters and flags only — no task text, prompt, canary or key | Pass | 0 |
| X8 | Course security checklist (§2.4) and deployment checklist (§3.6) | Below | 0 |

### X8 — course checklists

| Item | Status |
|---|---|
| Validate inputs, limit length, sanitize | Task 10–2,000 chars, control characters stripped, iterations 1–8, unknown fields rejected |
| Check for injection patterns, log suspicious inputs | Course patterns **flag** the run (`possible_injection`), logged by run id and pattern name |
| Scan outputs, redact secrets | Every worker result and the final answer; canary check on every LLM output |
| Validate output format | Protocol parser; strict schemas for Reviewer and Fact-Checker |
| Keys in environment variables | `GOOGLE_API_KEY` only on Railway, set via stdin; not in the repo or logs |
| Rate limiting per user | 3 runs/min, 15/day per IP; plus our daily cap (900) before Google's quota |
| Monitor usage, quota alerts | `/stats` (calls today, cache hit rate, cost estimate); service level `minimal` when the quota is used |
| Don't log sensitive data | X7 |
| Data retention | Runs, events and memories deleted after 30 days |
| HTTPS everywhere | Railway domain (TLS) |
| Authentication | **Not implemented** (lab scope: a public demo; rate limits and the daily cap bound the cost) |
| Health check, single source of config | `/health` + `railway.json`; all settings in `app/config.py` |
| Rollback plan | Below |

## Frontend connection (2026-10-10)

- Redeployed with `limits` in `/health` (needed by the UI).
- `FRONTEND_ORIGIN=http://localhost:3000,https://taller-research-agents.vercel.app`; CORS verified on preflight, a problem response and the SSE stream ([frontend/DEPLOY.md](../frontend/DEPLOY.md)).

## Redeploy / rollback

```bash
pytest -q && ruff check . && git commit ...        # gates + rollback point
railway up --detach --service backend --environment production
```

Rollback: Railway dashboard → `backend` → Deployments → previous deployment → Redeploy. The volume is not affected. Runs queued or running during a redeploy are marked failed at startup ("Interrupted by a server restart").
