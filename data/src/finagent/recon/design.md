# Recon — Design

## Purpose
Gather raw data on small-cap companies from free sources into a local store. Output feeds downstream modules.

## Docs
| Doc | Covers |
|---|---|
| [design/data-sources.md](design/data-sources.md) | Candidate free APIs and scrape targets |
| [design/ingestion.md](design/ingestion.md) | v0 pipeline: SEC EDGAR → SQLite, job runner, scheduling, schema, milestones |
| [design/data-model.md](design/data-model.md) | What is stored: files, tables, columns, sources, views, gotchas, live row counts |

## Decisions
- **Store:** SQLite (WAL), single local file (`data/finagent.db`).
- **First source:** SEC EDGAR (free, no key, authoritative).
- **Orchestration:** manual CLI first, then APScheduler, then Prefect/Dagster if needed.
- **Raw first:** save every response to disk before parsing; parsing can be replayed.

- **Small-cap definition:** market cap ≤ $2B, no lower bound.

## Status
M0–M2 built: `recon run <job>`, `recon schedule`, `recon reparse <job>`, `recon status`, views `v_recent_filings` and `v_latest_financials`. See [design/ingestion.md](design/ingestion.md) milestones.

## Open Questions
- Exchanges: NYSE/Nasdaq only, or include OTC?
- Refresh cadence per source.
