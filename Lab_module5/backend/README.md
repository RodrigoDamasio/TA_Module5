# Multi-Agent Research Assistant — backend

FastAPI service for [Lab 5](../Lab5_Multi_Agent_Orchestration.md): a **Supervisor** agent coordinates **Researcher**, **Writer**, **Reviewer** and **Fact-Checker** workers through the `DELEGATE` / `TASK` / `FINAL` protocol, and answers a research task with cited Wikipedia sources. Design: [PLAN.md](../PLAN.md) · [BACKEND_PLAN.md](../BACKEND_PLAN.md).

## Run locally

From this folder, with the shared virtual environment at the workspace root:

```bash
# demo mode: no API key, no quota, built-in Wikipedia articles
LLM_MODE=fake ../../../.venv/bin/uvicorn app.main:app --reload

# real Gemini + live Wikipedia (reads GOOGLE_API_KEY from the environment)
set -a; . ../../../.env; set +a
../../../.venv/bin/uvicorn app.main:app --reload
```

Then open http://localhost:8000/docs.

```bash
curl -X POST localhost:8000/run -H 'content-type: application/json' \
  -d '{"task": "When should I use RAG instead of fine-tuning?", "max_iterations": 5}'
# → 202 {"run_id": "run_…", "status_url": "/runs/run_…", "events_url": "/runs/run_…/events"}
curl -N localhost:8000/runs/<run_id>/events     # live progress (SSE)
curl localhost:8000/runs/<run_id>               # full state: transcript, final answer, sources
curl -X POST 'localhost:8000/run?wait=true' …   # synchronous: returns the finished run
```

## Endpoints

| Method · Path | Purpose |
|---|---|
| `POST /run` | Start a run: `{task, max_iterations?, require_approval?, use_memory?}` → `202` (or `200` with `?wait=true`) |
| `GET /runs/{id}` | Status, transcript (every decision and worker result), final answer, sources, flags, cost |
| `GET /runs/{id}/events` | Server-Sent Events: `run_started`, `agent_started`, `decision`, `worker_result`, `notice`, `feedback`, `awaiting_approval`, `completed` / `failed` / `cancelled` |
| `POST /runs/{id}/approve` · `/reject` | Human approval (extension); reject with `{feedback}` once to get a revision |
| `GET /agents` | The Supervisor and the worker registry |
| `GET /samples` · `GET /samples/{id}` | Stored completed runs (0 calls) |
| `GET /health` · `GET /stats` | Service level (`full` / `reduced` / `minimal`), usage, cost estimate, latency |
| `GET /problems/{slug}` | RFC 9457 problem types |

## Tests (0 real calls)

```bash
../../../.venv/bin/python -m pytest --cov=app        # 87 tests, ~95% coverage
../../../.venv/bin/ruff check . && ../../../.venv/bin/ruff format --check .
../../../.venv/bin/python -m pytest -m live_wiki     # opt-in: real Wikipedia, no Gemini
```

## Evaluation (real Gemini, opt-in)

```bash
LLM_MODE=fake ../../../.venv/bin/python -m eval.run          # checks the harness, 0 calls
../../../.venv/bin/python -m eval.run --max-calls 40 --export-samples
```

Scored deterministically (no LLM judge): completed without forcing, Researcher/Writer/Reviewer all ran, every `[n]` maps to a source, no canary or secret in any output, and the injection task is flagged and ignored. Responses and Wikipedia pages are cached in `eval/llm_cache.db`, so reruns are free.

**Results** (prompt v2, `gemini-3.5-flash-lite`, [eval/report.md](eval/report.md)): 3/3 tasks passed, protocol valid on first try 100%, 7–8 calls per run, injection flagged and ignored. What the first real run taught (prompt v1 → v2): [BACKEND_PLAN.md §19](../BACKEND_PLAN.md#19-implementation-notes-deviations-from-this-plan).

## Main settings

| Variable | Default | |
|---|---|---|
| `LLM_MODE` | `gemini` | `fake` = demo agents (no key) |
| `GEMINI_MODEL` · `MODEL_SUPERVISOR` · `MODEL_WORKERS` | `gemini-3.5-flash-lite` | Model routing per role |
| `WIKI_MODE` | `live` (`fake` with `LLM_MODE=fake`) | Wikipedia or built-in articles |
| `DEFAULT_MAX_ITERATIONS` · `MAX_ITERATIONS_LIMIT` | `5` · `8` | Supervisor decisions |
| `MAX_PARALLEL_DELEGATIONS` | `2` | Parallel workers (extension) |
| `RATE_LIMIT_RUNS_PER_MINUTE` · `_PER_DAY` | `3` · `15` | Per client IP |
| `LLM_DAILY_REQUEST_LIMIT` | `900` | Own cap before Google's quota |
| `MEMORY_ENABLED` | `true` | Memory (extension) |
| `DATABASE_PATH` | `research.db` | SQLite (Railway: `/data/research.db`) |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | CORS, comma-separated |

All settings: [app/config.py](app/config.py).
