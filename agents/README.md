# Agents

LangGraph + Claude workflows over FinAgent data. Design: [overall-design.md](src/finagent_agents/design/overall-design.md).

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env        # ANTHROPIC_API_KEY; FINAGENT_AGENTS_DATA_URL to use the data API
pytest
finagent-agents list
finagent-agents run company_brief -i ticker=SOUN
```

Data comes only from the data API (`../data`, `finagent-data serve`); importing the `finagent` package is a lint error.
