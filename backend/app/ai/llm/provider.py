from functools import lru_cache
from typing import AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("llm")

_PROVIDER_ALIASES = {
    "groq": "groq",
    "openrouter": "openai_compatible",
    "openai": "openai_compatible",
    "openai_compatible": "openai_compatible",
    "anthropic": "anthropic",
    "claude": "anthropic",
}

_DEFAULT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
}


@lru_cache
def _get_model(model_name: str, temperature: float) -> BaseChatModel:
    settings = get_settings()
    provider = _PROVIDER_ALIASES.get(settings.ai_provider.lower(), "groq")
    timeout = settings.llm_request_timeout_seconds

    if provider == "groq":
        from langchain_groq import ChatGroq

        api_key = settings.ai_api_key or settings.groq_api_key
        if not api_key:
            raise RuntimeError("No AI_API_KEY/GROQ_API_KEY configured.")

        kwargs = dict(
            model=model_name,
            temperature=temperature,
            api_key=api_key,
            timeout=timeout,
            max_retries=2,
            streaming=True,  # Enable streaming by default
        )
        try:
            if "reasoning_format" in getattr(ChatGroq, "model_fields", {}):
                kwargs["reasoning_format"] = "hidden"
            return ChatGroq(**kwargs)
        except Exception:
            kwargs.pop("reasoning_format", None)
            return ChatGroq(**kwargs)

    raise RuntimeError(f"Unsupported AI Provider: {settings.ai_provider}. Only Groq is supported.")


def get_llm(temperature: float = 0.2) -> BaseChatModel:
    settings = get_settings()
    logger.debug("LLM resolved: provider=%s model=%s", settings.ai_provider, settings.ai_model)
    return _get_model(settings.ai_model, temperature)


def get_fast_llm(temperature: float = 0.0) -> BaseChatModel:
    settings = get_settings()
    model_name = settings.ai_fast_model or settings.ai_model
    return _get_model(model_name, temperature)


async def stream_llm(messages: list[BaseMessage], temperature: float = 0.2) -> AsyncIterator[str]:
    """Stream LLM response token by token."""
    llm = get_llm(temperature)
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content


async def stream_fast_llm(messages: list[BaseMessage], temperature: float = 0.0) -> AsyncIterator[str]:
    """Stream fast LLM response token by token."""
    llm = get_fast_llm(temperature)
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield chunk.content