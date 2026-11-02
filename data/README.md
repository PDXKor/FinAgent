# Data

Data layer for FinAgent: one shared store, the jobs that fill it (recon), and its HTTP API. Part of the FinAgent monorepo; see the root README.

## Layout

| Path | Role |
|---|---|
| `src/finagent/data/` | Store: connection, schema, views, upsert, raw-response files. Domain-neutral. |
| `src/finagent/recon/` | Producer: SEC EDGAR ingestion jobs, runner, scheduler, `recon` CLI. |
| `src/finagent/api/` | HTTP API for FinAgent agents and FinAgentFrontEnd (data reads, recon job control): `finagent-data serve`. |
| `src/finagent/data/design.md` | Data layer design. |
| `src/finagent/recon/design.md` | Recon design. |

## Quick Start

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env        # set FINAGENT_SEC_USER_AGENT
pytest
recon run sec_tickers
recon status
finagent-data serve         # API at http://127.0.0.1:8765/v1
```
