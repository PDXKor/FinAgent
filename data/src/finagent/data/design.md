# Data Layer — Design

## Purpose
One store for all FinAgent data. Recon is one producer, not the owner. Agents and future sources plug into the same layer.

## Principles
- **Domain-neutral core.** `finagent.data` owns storage, schema, migrations, and the read API. It imports nothing from producers or consumers.
- **Producers write, consumers read.** Producers write through data-layer functions (`upsert` on natural keys). Consumers read through query functions, not ad-hoc SQL.
- **Every row is traceable.** Each table has a natural key, a `source`, and fetch/update timestamps.
- **Idempotent writes.** Re-running any producer is safe.
- **Raw first** (ingestion producers): save the response before parsing. Parsing can be replayed.

## Engine
SQLite, WAL mode, one file (`data/finagent.db`), stdlib `sqlite3`.
- Readers never block and are never blocked. Writers are serialized; a second writer waits `wait` seconds, then fails.
- Autocommit. `upsert` runs its batch in one transaction.
- No date types: dates and timestamps are ISO-8601 text, in and out. Compare and sort as text.
- Schema and views are reapplied on connect only when their text changed (hash in `PRAGMA user_version`).

## Domains

| Domain | Tables | Producer | Status |
|---|---|---|---|
| Reference | `companies`, `tickers` | recon (SEC) | built |
| Fundamentals | `filings`, `facts`, `public_float` | recon (SEC) | built |
| Ops | `ingest_runs`, `source_state` | recon runner | built |
| Market | prices, volume | new producer | planned |
| Agents | `agent_runs` | FinAgent agents (via API) | built |
| Curation | watchlists, notes | manual / CLI | planned (watchlist is a file today) |

Rule: a new domain adds tables and query functions to `finagent.data`; the producer lives in its own package next to `recon`.

## Layout

Now:
```
src/finagent/
  data/     db.py  raw.py  schema.sql  views.sql  timeutil.py
            queries/  reference.py  fundamentals.py  agents.py  ops.py
  recon/    jobs/  runner.py  pipeline.py  scheduler.py  cli.py
  api/      app.py  schemas.py  config.py  cli.py  jobs.py   # HTTP service over queries/ + recon jobs
```

Target:
```
src/finagent/
  data/
    db.py            # connect, upsert, locking
    raw.py           # raw response store
    migrations/      # numbered, applied once, recorded in a schema_version table
    queries/         # read API, one module per domain
  recon/             # SEC producer
  <producer>/        # market prices, etc.
```

## Consumer API
Consumers (FinAgent agents, FinAgentFrontEnd) run in other repos and processes. They reach the store over HTTP only; no shared code. `finagent.api` is a thin FastAPI layer over `finagent.data.queries`, plus recon job control.

```
FinAgent / FrontEnd ──HTTP /v1──► finagent.api ──► data.queries ──► SQLite (WAL)
                                       └─ jobs ──► recon ──► data.upsert ──┘
```

| Method | Path | Backed by |
|---|---|---|
| GET | `/v1/health` | — |
| GET | `/v1/companies/{ticker}` | `reference.get_company` (404 if unknown) |
| GET | `/v1/companies/{ticker}/financials?limit=8` | `fundamentals.get_financials` (limit ≤ 20) |
| PUT | `/v1/agent-runs/{run_id}` | `agents.save_agent_run` (idempotent upsert) |
| GET | `/v1/agent-runs/{run_id}` | `agents.get_agent_run` |
| GET | `/v1/jobs` | recon `REGISTRY` + `jobs.yaml` + `ops.latest_ingest_runs` |
| POST | `/v1/jobs/{name}/runs` | starts `recon.pipeline.ingest` in a thread; `202`, `409` if any job runs |
| GET | `/v1/ingest-runs?job=&limit=50` | `ops.list_ingest_runs` (limit ≤ 200) |
| GET | `/v1/ops/counts` | `ops.table_counts` |

- **Contract:** `api/schemas.py`. Add fields freely; breaking changes go to `/v2`.
- **Financials:** annual, from `v_annual_financials` (one row per fiscal year, 10-K; latest filing wins; shares from the year's original 10-K cover). Quarterly: later.
- **Connections:** one per request, opened and closed in the handler (sqlite3 is thread-bound; handlers run in a threadpool).
- **Writes:** wait `FINAGENT_API_LOCK_WAIT` (5s) for the writer lock, then `503` + `Retry-After`. Client retries.
- **Auth:** binds `127.0.0.1`. `FINAGENT_API_TOKEN` set → bearer token required.
- **Run:** `finagent-data serve` (`FINAGENT_API_HOST`, `FINAGENT_API_PORT`, default 8765).
- **Timestamps:** stored naive UTC; the API sends them with `Z`.
- **Jobs:** one at a time per API process (`api/jobs.py`); progress and results are `ingest_runs` rows. Waits `FINAGENT_JOB_LOCK_WAIT` (30s) for the writer lock. Needs `FINAGENT_SEC_USER_AGENT`. The API does not run the scheduler; a job killed with the server leaves a `running` row. This makes `api` depend on `recon`.
- **OpenAPI:** operation ids are route function names (clean generated clients).
- New endpoint = query function + schema + route, added when a consumer needs it.

## Open Questions
- **Migrations:** `schema.sql` is `CREATE IF NOT EXISTS` only. Column changes need versioned migrations (`PRAGMA user_version` is taken by the schema hash today).
- **Watchlist:** stays a file, or moves into the Curation tables.
