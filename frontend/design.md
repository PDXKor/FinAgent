# FinAgentFrontEnd — Design

## Purpose
Browser UI over two backends: browse data from **FinAgentData**, launch and watch workflows from **FinAgent**. Single user, local first.

## System

```
Browser (SPA) ──same origin──► proxy (:5173 dev / :8080 prod)
                                 ├─ /api/data/*   ──► finagent-data serve   :8765  ──► SQLite (WAL)
                                 └─ /api/agents/* ──► finagent-agents serve :8766  ──► Runner ─► Claude
                                                                                   └─► FinAgentData /v1 (save_run, tools)
```

| Backend | Owns | UI uses it for |
|---|---|---|
| FinAgentData | All stored data, incl. `agent_runs` | Companies, financials, filings, screens, run history, ingest status |
| FinAgent | Workflows, live runs | Workflow catalog, start run, live events, cancel |

Rules:
- **Data reads go to FinAgentData only.** Run history included. FinAgent serves only what is live (catalog, in-flight runs).
- **No CORS, no tokens in the browser.** The proxy strips the prefix and injects each backend's bearer token.
- **Types come from OpenAPI.** Both backends are FastAPI; `openapi-typescript` generates TS types. A contract change fails `tsc`.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Build | Vite + TypeScript (strict) | Fast, static output, dev proxy built in |
| UI | React 19 | Ecosystem; component libs |
| Routing | TanStack Router | Typed routes and search params (filters live in the URL) |
| Server state | TanStack Query | Cache, retry, polling; no global store needed |
| Styling | Tailwind + shadcn/ui | Owned components, no runtime theme lib |
| Tables | TanStack Table | Sort/filter for screener and runs |
| Charts | Recharts | Enough for annual bars/lines |
| Markdown | react-markdown, no raw HTML | Briefs are LLM output; never render HTML from it |
| API types | openapi-typescript + openapi-fetch | Generated, thin client |
| Tests | Vitest + Testing Library + MSW; Playwright e2e | Fake both APIs in unit tests |
| Prod proxy | Caddy | One file, serves `dist/` and proxies |

Prerequisite: Node 22 LTS (not installed on this machine yet).

## Layout

```
FinAgentFrontEnd/
  design.md
  package.json  vite.config.ts  tsconfig.json  Caddyfile  .env.example
  src/
    main.tsx  router.tsx
    api/
      data.ts  agents.ts          # openapi-fetch clients, base /api/data, /api/agents
      generated/data.d.ts         # npm run gen:api (from :8765/openapi.json)
      generated/agents.d.ts       # (from :8766/openapi.json)
      queries.ts                  # TanStack Query hooks; only place that calls clients
      events.ts                   # SSE hook for live runs
    routes/
      index.tsx                   # dashboard
      screener.tsx
      companies.$ticker.tsx
      workflows.tsx  workflows.$name.tsx
      runs.tsx  runs.$runId.tsx
      ops.tsx
      watchlist.tsx
    components/                   # ui/ (shadcn), RunStatus, MoneyCell, InputForm, Markdown, ...
    lib/format.ts                 # money, %, ISO-UTC -> local
  tests/  e2e/
```

## Pages

| Route | Shows | Actions | Backend calls |
|---|---|---|---|
| `/` | Last runs, ingest job status, table counts | — | data: runs list, ops |
| `/screener` | `v_small_cap_candidates`; filter float range, exchange, SIC, location | Select tickers → run `screen_then_brief`; add to watchlist | data: screens; agents: start run |
| `/companies/:ticker` | Profile, annual financials table + charts, recent filings, past briefs for ticker | Run `company_brief` | data: company, financials, filings, runs?ticker; agents: start run |
| `/workflows` | Catalog: graph, inputs, node bindings (model, effort, prompt, tools), timeout, schedule | — | agents: workflows |
| `/workflows/:name` | Form generated from input schema | Start run (confirm dialog shows models) | agents: start run |
| `/runs` | Run history; filter workflow, status, ticker, date | — | data: runs list |
| `/runs/:runId` | Status, inputs, bindings, tokens, duration, output (markdown) or error; live timeline while running | Cancel | data: run; agents: events, cancel |
| `/ops` | Latest ingest run per job, schedule, table counts | — (trigger jobs: later) | data: ops |
| `/watchlist` | Tickers | Add/remove | data: watchlist |

Input form: map workflow input types to controls — `str` text, `int`/`float` number, `bool` switch, `list[str]` ticker multi-select (typeahead from company search).

## Live Runs
1. `POST /api/agents/v1/workflows/{name}/runs` → `202 {run_id}`. Run record already saved as `running` in FinAgentData.
2. Navigate to `/runs/{run_id}`. Open `EventSource /api/agents/v1/runs/{run_id}/events`.
3. Events: `node_start`, `node_end`, `tool_call`, `tool_result`, `token`, `done`. Timeline shows nodes and tool calls; streams output text.
4. On `done`, close stream; refetch the run from FinAgentData (source of truth).
5. Stream unavailable (agents server restarted, run finished long ago) → fall back to polling the data run every 3s until terminal status.

## State and Data Rules
- Server state only in TanStack Query. Keys mirror API paths. URL search params hold filters.
- Terminal runs: `staleTime: Infinity`. Running runs: poll as above. Reference data: 5 min.
- Timestamps: API sends UTC with offset; UI shows local time, tooltip shows UTC.
- Money: compact (`$1.2B`), full value in tooltip. Nulls render `—`, never `0`.
- `503` from data API: Query retries with backoff (honor `Retry-After`).

## Security
- Backends bind `127.0.0.1`. Only the proxy is exposed, and only on localhost unless auth is added.
- Tokens in proxy env (`FINAGENT_DATA_TOKEN`, `FINAGENT_AGENTS_TOKEN`), never in the bundle.
- Run triggers cost money: confirm dialog with models and effort; agents API enforces its own limits.
- Markdown: no `rehype-raw`; links open with `rel="noopener noreferrer"`.

## Required Changes — FinAgentData

| # | Change | Why |
|---|---|---|
| D1 | `GET /v1/agent-runs?workflow=&status=&ticker=&before=&limit=` → `{items, next}`, newest first. Ticker matches `$.ticker` or any of `$.tickers` via `json_extract`/`json_each`. Index `agent_runs(started_at)`, `(workflow, started_at)`. | Runs page, company briefs, dashboard |
| D2 | `GET /v1/companies?q=&limit=` — ticker/name prefix search | Typeahead |
| D3 | `GET /v1/screens/small-caps?min_float=&max_float=&exchange=&sic=&location=&limit=&offset=` over `v_small_cap_candidates` | Screener |
| D4 | `GET /v1/companies/{ticker}/filings?form=&limit=` over `v_recent_filings` | Company page |
| D5 | `queries/ops.py`: latest `ingest_runs` per job + table counts; `GET /v1/ops/status`. `recon status` reuses it. | Ops page; removes SQL from CLI |
| D6 | **Timestamp bug:** `agent_runs` stores naive UTC and the API returns it without offset; browsers parse that as local time. Serialize all datetimes as UTC with `Z` (schema-level serializer). | Correct times in UI |
| D7 | Add `cancelled` to `AgentRunIn.status`. | Cancel support (A3) |
| D8 | Watchlist moves to Curation: table `watchlist(ticker PK, added_at, note)`; `GET/PUT/DELETE /v1/watchlist[/{ticker}]`. Recon reads the table; `slice.txt` imported once. | Edit from UI; closes design open question |
| D9 | Set FastAPI `generate_unique_id_function` to route name. | Clean generated client names |
| D10 | Commit the `http-api` branch work (API, queries) and add a git remote. | UI depends on it |

List endpoints use `{items, next}`; existing bare-list endpoints stay as-is in `/v1` (additive only).

## Required Changes — FinAgent

| # | Change | Why |
|---|---|---|
| A1 | `finagent-agents serve` (FastAPI + uvicorn, `:8766`). Lifespan owns one `HttpDataLayer` and one `Runner`. Endpoints: `GET /v1/health`, `GET /v1/workflows`, `POST /v1/workflows/{name}/runs` (422 on bad input), `GET /v1/runs/{id}/events` (SSE), `POST /v1/runs/{id}/cancel`. Bearer token via `FINAGENT_AGENTS_API_TOKEN`. | UI has no way to start runs today (CLI only) |
| A2 | `Runner.start(name, inputs) -> run_id`: validate, save `running`, spawn task, return. Keep `run`/`run_many` for CLI. Track tasks by `run_id`. | Non-blocking start |
| A3 | Cancel: `task.cancel()` → status `cancelled`, `finished_at` set, saved. Add `cancelled` to `RunRecord.status`. | Stop runaway or costly runs |
| A4 | Events: run graph with `astream_events` (or `astream` with `updates` + `messages`) instead of `ainvoke`; publish to a per-run in-memory broadcaster; SSE subscribers read it. Usage counting unchanged. Not persisted (deferred). | Live timeline |
| A5 | `Workflow.describe()` exposes `input` types, `timeout_s`, `max_concurrency`, `schedule` — not just node bindings. | Catalog + generated forms |
| A6 | On server start, mark stale `running` runs (from D1 `status=running`) as `failed: interrupted`. Single agents process assumed. | No zombie "running" rows after restart |
| A7 | Add `python-dotenv` to dependencies (`cli.py` imports it; not declared). Add `fastapi`, `uvicorn`, `sse-starlette`. | Clean install fails today |
| A8 | Cleanup: remove the duplicated `src/finagent/{data,recon}`, `tests/{data,recon}`, `data/`, `duckdb` binary, `venv/` from the `data-layer` branch (now in FinAgentData). Rewrite stale README and Dockerfile (`finagent serve` entrypoint no longer exists). Trim `.env.example` to `FINAGENT_AGENTS_*`. | Repo matches the agents-only split |

## Milestones

| # | Scope | Depends on |
|---|---|---|
| F0 | Scaffold, Vite proxy, generated types, health badges for both APIs | Node install, D9, D10 |
| F1 | Company page, screener, typeahead (read-only) | D2, D3, D4, D6 |
| F2 | Runs list + detail (history, no live) | D1 |
| F3 | Workflow catalog, generated forms, start run, live timeline, cancel | A1–A7, D7 |
| F4 | Ops page, watchlist editing | D5, D8 |
| F5 | Caddy prod config, Playwright e2e, empty/error states | — |

## Test Plan
- **Unit/component (Vitest + MSW):** formatters, input-form mapping per type, run status rendering, query hooks against MSW handlers built from generated types.
- **Contract:** CI regenerates types from both running backends; `tsc` fails on drift.
- **E2E (Playwright):** both backends with temp DB and fake LLM (`MemoryDataLayer` not used; real data API on fixture DB). Flows: open company → start brief → see live events → final output; screener select → `screen_then_brief`.

## Deferred
| Capability | Until then |
|---|---|
| Persisted run events / trace | Live only; history shows final output and tokens |
| Trigger recon jobs from UI | `recon run` CLI |
| Multi-user auth | Localhost only, proxy-held tokens |
| Human-in-the-loop approvals | Needs persistent checkpointer in FinAgent |
| Market prices | Float as market-cap proxy |

## Open Questions
- One proxy process, or let FinAgent API also proxy data reads? Recommendation: separate proxy; keeps backends independent.
- Deploy target beyond localhost (VM + Caddy vs. containers for all three).
