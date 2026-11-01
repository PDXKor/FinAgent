# Data Layer — Design

## Purpose
One store for all FinAgent data. Recon is one producer, not the owner. Agents and future sources plug into the same layer.

## Principles
- **Domain-neutral core.** `finagent.data` owns storage, schema, migrations, and the read API. It imports nothing from producers or consumers.
- **Producers write, consumers read.** Producers write through data-layer functions (`upsert` on natural keys). Consumers read through query functions, not ad-hoc SQL.
- **Every row is traceable.** Each table has a natural key, a `source`, and fetch/update timestamps.
- **Idempotent writes.** Re-running any producer is safe.
- **Raw first** (ingestion producers): save the response before parsing. Parsing can be replayed.

## Domains

| Domain | Tables | Producer | Status |
|---|---|---|---|
| Reference | `companies`, `tickers` | recon (SEC) | built |
| Fundamentals | `filings`, `facts`, `public_float` | recon (SEC) | built |
| Ops | `ingest_runs`, `source_state` | recon runner | built |
| Market | prices, volume | new producer | planned |
| Agents | `agent_runs`, agent outputs | FinAgent agents | planned |
| Curation | watchlists, notes | manual / CLI | planned (watchlist is a file today) |

Rule: a new domain adds tables and query functions to `finagent.data`; the producer lives in its own package next to `recon`.

## Layout

Now:
```
src/finagent/
  data/     db.py  raw.py  schema.sql  views.sql  timeutil.py
  recon/    jobs/  runner.py  pipeline.py  scheduler.py  cli.py
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
Not designed yet. FinAgent agents will consume it. Constraints known today:
- Agents read reference, fundamentals and market data, and write agent runs and outputs.
- Agents run concurrently. The store must allow reads while a producer writes.
- Agents must not depend on table layout. They call query functions only.

## Open Questions
- **Engine:** DuckDB allows one process at a time, so a scheduled recon run blocks every reader. The prior session planned SQLite in WAL mode (concurrent readers, one writer); no code exists for it yet. Decide before adding consumers.
- **Migrations:** `schema.sql` is `CREATE IF NOT EXISTS` only. Column changes need versioned migrations.
- **Distribution:** how FinAgent depends on this package (editable path install, git dependency, or a service).
- **Watchlist:** stays a file, or moves into the Curation tables.
