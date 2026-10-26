# FinAgent

Cloud-neutral LangGraph agents that retrieve financial information on a schedule and write a brief.

## Layout

- `src/finagent/graph.py` – LangGraph workflow (`fetch` → `summarize`)
- `src/finagent/llm/` – pluggable LLM layer (Anthropic, OpenAI, Ollama; `register_provider` for more)
- `src/finagent/sources/` – pluggable data sources (`yfinance` by default; `register_source` for more)
- `src/finagent/runner.py` – runs the graph once and writes `reports/report-<timestamp>.md`
- `src/finagent/cli.py` – `finagent run` (one-shot) and `finagent serve` (built-in cron scheduler)

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[ollama,dev]"                       # or anthropic / openai
cp .env.example .env
pytest
finagent run
```

## Deploying anywhere

- **Anywhere with a long-running process** (VM, Docker, local): `finagent serve`.
- **Platform schedulers** (cron, systemd timer, Kubernetes CronJob, Cloud Run/ECS jobs, GitHub Actions): run `finagent run`.
- Docker: `docker build --build-arg LLM_EXTRA=anthropic -t finagent .`
- All config is `FINAGENT_*` environment variables; see `.env.example`.
