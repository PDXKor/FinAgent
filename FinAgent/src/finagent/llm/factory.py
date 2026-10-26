"""Pluggable LLM layer.

The rest of the codebase only depends on LangChain's ``BaseChatModel`` interface. Providers are
imported lazily so you only need the extra for the one you use (``pip install finagent[openai]``).
Add your own with ``register_provider``.
"""

from typing import Callable

from langchain_core.language_models.chat_models import BaseChatModel

from finagent.config import Settings, get_settings

Builder = Callable[[Settings], BaseChatModel]


def _anthropic(s: Settings) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=s.llm_model, temperature=s.llm_temperature, base_url=s.llm_base_url)


def _openai(s: Settings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=s.llm_model, temperature=s.llm_temperature, base_url=s.llm_base_url)


def _ollama(s: Settings) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    kwargs = {"base_url": s.llm_base_url} if s.llm_base_url else {}
    return ChatOllama(model=s.llm_model, temperature=s.llm_temperature, **kwargs)


_PROVIDERS: dict[str, Builder] = {
    "anthropic": _anthropic,
    "openai": _openai,
    "ollama": _ollama,
}


def register_provider(name: str, builder: Builder) -> None:
    _PROVIDERS[name.lower()] = builder


def get_llm(settings: Settings | None = None) -> BaseChatModel:
    settings = settings or get_settings()
    name = settings.llm_provider.lower()
    try:
        builder = _PROVIDERS[name]
    except KeyError:
        raise ValueError(f"Unknown LLM provider {name!r}. Available: {sorted(_PROVIDERS)}") from None
    return builder(settings)
