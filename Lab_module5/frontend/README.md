# Multi-Agent Research Assistant — frontend

Next.js 16 UI for [Lab 5](../Lab5_Multi_Agent_Orchestration.md): a chat where a research task is answered by a Supervisor agent and its workers, with a live **agent board**, an **activity feed**, the **transcript** of Supervisor decisions and worker results, and the final **Markdown answer** with linked Wikipedia sources. Design: [FRONTEND_PLAN.md](../FRONTEND_PLAN.md). API: [backend/README.md](../backend/README.md).

## Run locally

Node 24 (`source ~/.nvm/nvm.sh && nvm use 24`). `next dev` hits this machine's file-watch limit, so use a production build:

```bash
# backend in demo mode (no key, no quota), from ../backend:
LLM_MODE=fake FAKE_LLM_DELAY_S=0.4 ../../../.venv/bin/uvicorn app.main:app --port 8000
# frontend:
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build && npm run start   # http://localhost:3000
```

## Tests (0 real AI calls)

```bash
npm run typecheck && npm run lint
npm run test:coverage                       # 45 unit/component tests, ~95 % lines
npm run test:e2e                            # 6 E2E: starts the fake backend + the production build
BASE_URL=https://<vercel-domain> npm run test:e2e   # production subset (samples, phone, axe, one real run)
```

The fixtures are the real stored runs from `backend/samples/runs/`, parsed with the frontend's schemas.

## What it shows

| Lab requirement | Where |
|---|---|
| Chat-like interface | Conversation thread + composer (Enter sends), run settings, sample chips |
| Real-time agent activity | Agent board (state as text, timers, two cards working in parallel) + activity feed, from SSE |
| Conversation history | Transcript: decisions (REASON, DELEGATE/TASK, FINAL), worker results, review verdict, fact-check table, notices, feedback |
| Final output panel | Markdown answer, `[n]` links to sources, flags, copy / download, meta bar (calls, tokens, est. cost) |
| Responsive | Two columns on wide screens; tabs Answer · Agents · Transcript on phones |

Also: human approval panel, memory links, service banner (`reduced` / `minimal` / `offline`), injection notice, `?run=` resume, thread kept in the browser.
