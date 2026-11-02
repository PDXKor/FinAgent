# FinAgent

Small-cap financial research: SEC data ingestion, LLM agent workflows, and a web UI.

## Layout

| Path | Package | Role | Design |
|---|---|---|---|
| `data/` | `finagent-data` (Python) | SQLite store, recon ingestion jobs, HTTP API (`finagent-data serve`, :8765) | [data](data/src/finagent/data/design.md), [recon](data/src/finagent/recon/design.md) |
| `agents/` | `finagent-agents` (Python) | LangGraph + Claude workflows (`finagent-agents`) | [agents](agents/src/finagent_agents/design/overall-design.md) |
| `frontend/` | `finagent-frontend` (npm) | React UI behind a same-origin proxy (:5173) | [frontend](frontend/design.md) |

```
frontend ──/api/data──► data API ──► SQLite ◄── recon jobs
agents ──HTTP /v1─────►     │
```

## Rules
- **HTTP is the only link.** `agents/` and `frontend/` reach data through the data API. No package imports another; `agents/` enforces it with ruff `TID251`.
- **One package, one toolchain.** Each package has its own `pyproject.toml`/`package.json`, venv or `node_modules`, `.env`, and tests. Run commands from the package folder.
- **Contract changes land in one commit:** API route + schema in `data/`, then regenerated types in `frontend/` (`npm run gen:api`) and client methods in `agents/`.

## Quick Start (Windows)

```bash
cd data     && python -m venv .venv && .venv\Scripts\pip install -e ".[dev]" && cd ..
cd agents   && python -m venv .venv && .venv\Scripts\pip install -e ".[dev]" && cd ..
cd frontend && npm install && cd ..
```

Run (one terminal each): `data> finagent-data serve`, `frontend> npm run dev`. Each package README has details.
