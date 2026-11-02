from finagent_agents.tools.company import MAX_FINANCIAL_ROWS, get_company, get_financials

# name -> factory(data_layer) -> BaseTool
TOOLS = {
    "get_company": get_company,
    "get_financials": get_financials,
}

__all__ = ["MAX_FINANCIAL_ROWS", "TOOLS"]
