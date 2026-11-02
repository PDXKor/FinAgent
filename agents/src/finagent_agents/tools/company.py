from langchain_core.tools import BaseTool, tool

from finagent_agents.data import DataLayer

MAX_FINANCIAL_ROWS = 20  # keeps tool results small; big results waste tokens


def get_company(data: DataLayer) -> BaseTool:
    @tool("get_company")
    async def _get_company(ticker: str) -> dict:
        """Look up a company profile (name, CIK, industry) by ticker. Returns {} if unknown."""
        return await data.get_company(ticker.strip().upper()) or {}

    return _get_company


def get_financials(data: DataLayer) -> BaseTool:
    @tool("get_financials")
    async def _get_financials(ticker: str, limit: int = 8) -> list[dict]:
        """Recent reported financials for a ticker, newest period first. Empty if none."""
        return await data.get_financials(ticker.strip().upper(), min(limit, MAX_FINANCIAL_ROWS))

    return _get_financials
