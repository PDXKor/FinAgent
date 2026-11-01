# FinAgentData

Data layer for FinAgent: one shared store plus the jobs that fill it. Agents live in the separate FinAgent repo.

## Layout

| Path | Role |
|---|---|
| `src/finagent/data/` | Store: connection, schema, views, upsert, raw-response files. Domain-neutral. |
| `src/finagent/recon/` | Producer: SEC EDGAR ingestion jobs, runner, scheduler, `recon` CLI. |
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
```
