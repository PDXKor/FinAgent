# Frontend — Design

## Purpose
Browser UI over two backends in this monorepo: browse data from the **data API** (`data/`, "FinAgentData"), launch and watch workflows from **agents** (`agents/`, "FinAgent"). Single user, local first.

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
| Build | Vite + TypeScript 5 (strict) | Fast, static output, dev proxy built in. TS 5 because openapi-typescript requires it |
| UI | React 19 | Ecosystem; component libs |
| Routing | TanStack Router (from the second page) | Typed routes and search params (filters live in the URL) |
| Server state | TanStack Query | Cache, retry, polling; no global store needed |
| Styling | Tailwind 4; shadcn/ui when components outgrow hand-written ones | Owned components, no runtime theme lib |
| Tables | TanStack Table | Sort/filter for screener and runs |
| Charts | Recharts | Enough for annual bars/lines |
| Markdown | react-markdown, no raw HTML | Briefs are LLM output; never render HTML from it |
| API types | openapi-typescript + openapi-fetch | Generated, thin client |
| Tests | Vitest + Testing Library + MSW; Playwright e2e | Fake both APIs in unit tests |
| Prod proxy | Caddy (`frontend/Caddyfile`, in the frontend image) | One file, serves `dist/` and proxies |

Prerequisite: Node LTS (v26; per-user install in `%LOCALAPPDATA%\Programs\nodejs`). Dependencies installed with `npm install --before=<date ≥ 2 weeks ago>`.

## Layout

Built (ingestion):
```
frontend/
  package.json  vite.config.ts  tsconfig.json  .env.example
  src/
    main.tsx  App.tsx  index.css
    api/
      data.ts                     # openapi-fetch client (base /api/data), ApiError, unwrap
      generated/data.d.ts         # npm run gen:api (from :8765/openapi.json)
      queries.ts                  # TanStack Query hooks; only place that calls clients
    pages/Ingestion.tsx (+ .test.tsx)
    components/StatusBadge.tsx
    lib/format.ts  useNow.ts
    test/                         # MSW server, setup, render helper
```

Target adds:
```
  Caddyfile
  src/
    router.tsx
    api/agents.ts  generated/agents.d.ts  events.ts   # FinAgent client, SSE hook
    pages/  screener  company  workflows  runs  watchlist
    components/ui/                                   # shadcn
  e2e/
```

## Pages

| Route | Shows | Actions | Backend calls |
|---|---|---|---|
| `/` | Last runs, ingest job status, table counts | — | data: runs list, jobs |
| `/screener` | `v_small_cap_candidates`; filter float range, exchange, SIC, location | Select tickers → run `screen_then_brief`; add to watchlist | data: screens; agents: start run |
| `/companies/:ticker` | Profile, annual financials table + charts, recent filings, past briefs for ticker | Run `company_brief` | data: company, financials, filings, runs?ticker; agents: start run |
| `/workflows` | Catalog: graph, inputs, node bindings (model, effort, prompt, tools), timeout, schedule | — | agents: workflows |
| `/workflows/:name` | Form generated from input schema | Start run (confirm dialog shows models) | agents: start run |
| `/runs` | Run history; filter workflow, status, ticker, date | — | data: runs list |
| `/runs/:runId` | Status, inputs, bindings, tokens, duration, output (markdown) or error; live timeline while running | Cancel | data: run; agents: events, cancel |
| `/ingestion` (built; `/` today) | Recon jobs in dependency order: status, schedule, last run numbers, errors; table counts; run history filtered by job | Run a job (one at a time) | data: jobs, ingest-runs, counts |
| `/watchlist` | Tickers | Add/remove | data: watchlist |

Input form: map workflow input types to controls — `str` text, `int`/`float` number, `bool` switch, `list[str]` ticker multi-select (typeahead from company search).

## Live Runs
1. `POST /api/agents/v1/workflows/{name}/runs` → `202 {run_id}`. Run record already saved as `running` in FinAgentData.
2. Navigate to `/runs/{run_id}`. Open `EventSource /api/agents/v1/runs/{run_id}/events`.
3. Events: `run_start`, `node_*`, `llm_*`, `tool_*`, `done`, each with `span`/`parent` for a tree (agents design, Server). Timeline shows nodes, model calls and tool calls. Token streaming: deferred.
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

## Required Changes — data/ (FinAgentData)

| # | Change | Why |
|---|---|---|
| D1 | **Partly done.** `GET /v1/agent-runs?workflow=&status=&before=&limit=` → `{items, next}`, index on `started_at`. Still to add: `ticker` filter (`$.ticker` or any of `$.tickers`). | Runs page, company briefs, dashboard |
| D2 | `GET /v1/companies?q=&limit=` — ticker/name prefix search | Typeahead |
| D3 | `GET /v1/screens/small-caps?min_float=&max_float=&exchange=&sic=&location=&limit=&offset=` over `v_small_cap_candidates` | Screener |
| D4 | `GET /v1/companies/{ticker}/filings?form=&limit=` over `v_recent_filings` | Company page |
| D5 | **Done.** `queries/ops.py` (latest run per job, run list, table counts); `recon status` reuses it. | Ingestion page; removes SQL from CLI |
| D6 | **Done.** Timestamps were sent without offset (browsers read them as local). `UtcDatetime` schema type now sends `Z`. | Correct times in UI |
| D7 | **Done.** `cancelled` status. | Cancel support (A3) |
| D8 | Watchlist moves to Curation: table `watchlist(ticker PK, added_at, note)`; `GET/PUT/DELETE /v1/watchlist[/{ticker}]`. Recon reads the table; `slice.txt` imported once. | Edit from UI; closes design open question |
| D9 | **Done.** Operation ids = route names. | Clean generated client names |
| D10 | **Done.** Work committed; merged into the monorepo with history. | UI depends on it |
| D11 | **Done.** Recon job control: `GET /v1/jobs`, `POST /v1/jobs/{name}/runs` (background thread, one job at a time, `409` when busy), `GET /v1/ingest-runs`, `GET /v1/ops/counts`. `recon.pipeline.ingest` returns `RunResult` or raises. | Ingestion page |
| D12 | Mark stale `running` ingest rows `failed` on API start (job threads die with the server). | No zombie "running elsewhere" rows |
| D13 | Progress counters during a run (runner updates `requests`/`rows_written` every N requests). | Live progress for long jobs |

List endpoints use `{items, next}`; existing bare-list endpoints stay as-is in `/v1` (additive only).

## Required Changes — agents/ (FinAgent)

| # | Change | Why |
|---|---|---|
| A1 | **Done.** `finagent-agents serve` (`:8766`): health, workflows, start (`202`), SSE events, cancel. Bearer `FINAGENT_AGENTS_API_TOKEN`. | Start runs from the UI |
| A2 | **Done.** `Runner.start` → running record; background task tracked by `run_id`. | Non-blocking start |
| A3 | **Done.** Cancel → `cancelled`, `finished_at`, saved; shutdown cancels in-flight runs. | Stop runaway or costly runs |
| A4 | **Done.** Callback-based events (graph still runs with `ainvoke`) into a per-run replayable stream; SSE with `Last-Event-ID`. Not persisted. | Live timeline |
| A5 | **Done.** `/v1/workflows` returns input types, bindings, timeout, concurrency, schedule. | Catalog + generated forms |
| A6 | **Done.** Startup marks stale `running` runs `failed: interrupted`. | No zombie rows |
| A7 | `python-dotenv` added (**done**). Add `fastapi`, `uvicorn`, `sse-starlette` with A1. | Clean install |
| A8 | **Done.** Duplicated data/recon removed, stale Dockerfile dropped, `.env.example` trimmed, agents moved to `agents/`. Root README covers the monorepo. | Repo matches the split |

## Milestones

| # | Scope | Depends on |
|---|---|---|
| F0 | **Done.** Scaffold, Vite proxy, generated types, data API health badge | D9 |
| F0.5 | **Done.** Ingestion page: run recon jobs, status, history, counts | D5, D6, D11 |
| F1 | Router, company page, screener, typeahead (read-only) | D2, D3, D4 |
| F2 | Runs list + detail (history, no live) | D1 |
| F3 | Workflow catalog, generated forms, start run, live timeline, cancel (backend ready) | A1–A6, D7 (done) |
| F4 | Watchlist editing, ingest progress | D8, D12, D13 |
| F5 | Containers + Caddy (**done**: `compose.yaml`); Playwright e2e, empty/error states | — |

## Test Plan
- **Unit/component (Vitest + MSW):** formatters, input-form mapping per type, run status rendering, query hooks against MSW handlers built from generated types.
- **Contract:** CI regenerates types from both running backends; `tsc` fails on drift.
- **E2E (Playwright):** both backends with temp DB and fake LLM (`MemoryDataLayer` not used; real data API on fixture DB). Flows: open company → start brief → see live events → final output; screener select → `screen_then_brief`.

## Deferred
| Capability | Until then |
|---|---|
| Persisted run events / trace | Live only; history shows final output and tokens |
| Reparse and schedule control from UI | `recon reparse` / `recon schedule` CLI |
| Multi-user auth | Localhost only, proxy-held tokens |
| Human-in-the-loop approvals | Needs persistent checkpointer in FinAgent |
| Market prices | Float as market-cap proxy |

## Open Questions
- One proxy process, or let FinAgent API also proxy data reads? Recommendation: separate proxy; keeps backends independent.
- Deploy target beyond localhost: compose runs locally today; same images on a VM (add auth before exposing beyond localhost).
