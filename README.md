# FinAgent

Small-cap financial research: SEC data ingestion, LLM agent workflows, and a web UI.

## Layout

| Path | Package | Role | Design |
|---|---|---|---|
| `data/` | `finagent-data` (Python) | SQLite store, recon ingestion jobs, HTTP API (`finagent-data serve`, :8765) | [data](data/src/finagent/data/design.md), [recon](data/src/finagent/recon/design.md) |
| `agents/` | `finagent-agents` (Python) | LangGraph + Claude workflows; HTTP API (`finagent-agents serve`, :8766) | [agents](agents/src/finagent_agents/design/overall-design.md) |
| `frontend/` | `finagent-frontend` (npm) | React UI behind a same-origin proxy (:5173) | [frontend](frontend/design.md) |

```
browser ─► frontend (proxy) ─┬─ /api/data ───► data API ──► SQLite ◄── recon jobs
                             └─ /api/agents ─► agents API ─(HTTP /v1)─► data API
```

## Rules
- **HTTP is the only link.** `agents/` and `frontend/` reach data through the data API. No package imports another; `agents/` enforces it with ruff `TID251`.
- **One package, one toolchain.** Each package has its own `pyproject.toml`/`package.json`, venv or `node_modules`, `.env`, and tests. Run commands from the package folder.
- **Contract changes land in one commit:** API route + schema in `data/`, then regenerated types in `frontend/` (`npm run gen:api`, from source) and client methods in `agents/`. CI fails on stale types.
- **Pinned dependencies:** Python installs use each package's `constraints.txt`; Docker images use exact tags. Refresh constraints with `pip freeze --exclude-editable` after changing dependencies.
- **Browser safety:** the proxies add tokens, so both APIs refuse cross-site browser requests (`Sec-Fetch-Site`) and unknown `Host` headers (`*_API_ALLOWED_HOSTS`). `/docs` is off when a token is set.
- **CI** (`.github/workflows/ci.yml`): lint, format, tests per package; front-end build; API-type drift.

## Docker

| Service | Image | Port (localhost only) | Runs |
|---|---|---|---|
| `data` | `data/Dockerfile` (Python) | 8765 | API + recon jobs; state in volume `finagent_finagent-data` at `/data` |
| `frontend` | `frontend/Dockerfile` (Node build → Caddy) | 8080 | SPA + `/api/data`, `/api/agents` proxy (adds tokens) |
| `agents` | `agents/Dockerfile` (Python) | 8766 | Agents API; same image runs one-off CLI commands |

```bash
cp .env.example .env                 # optional: FINAGENT_API_TOKEN shared by all services
docker compose up --build -d         # UI at http://localhost:8080
docker compose run --rm agents run company_brief -i ticker=SOUN
docker compose logs -f data
```

- Secrets stay in `data/.env` (`FINAGENT_SEC_USER_AGENT`) and `agents/.env` (`ANTHROPIC_API_KEY`); compose overrides their paths and URLs for containers.
- SQLite lives in a named volume, not a Windows bind mount (WAL locking needs a Linux filesystem).
- Seed the volume from local data (stop local `finagent-data serve` first; port 8765 is shared):
  `docker compose run --rm --no-deps -v ./data/data:/seed:ro data sh -c "cp -r /seed/. /data/"`
- Fresh volume: add a watchlist before running `sec_submissions`/`sec_companyfacts`:
  `docker compose exec data sh -c 'printf "SOUN\nBBAI\n" > /data/slice.txt'`
- Development stays local (`npm run dev`, package venvs); compose is for running the app.

## Quick Start (Windows)

```bash
cd data     && python -m venv .venv && .venv\Scripts\pip install -e ".[dev]" -c constraints.txt && cd ..
cd agents   && python -m venv .venv && .venv\Scripts\pip install -e ".[dev]" -c constraints.txt && cd ..
cd frontend && npm install && cd ..
```

Run (one terminal each): `data> finagent-data serve`, `agents> finagent-agents serve`, `frontend> npm run dev`. Each package README has details.
