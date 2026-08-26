from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("llm")

_PROVIDER_ALIASES = {
    "groq": "groq",
    "openrouter": "openai_compatible",
    "openai": "openai_compatible",
    "openai_compatible": "openai_compatible",
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
        )
        try:
            if "reasoning_format" in getattr(ChatGroq, "model_fields", {}):
                kwargs["reasoning_format"] = "hidden"
            return ChatGroq(**kwargs)
        except Exception:
            kwargs.pop("reasoning_format", None)
            return ChatGroq(**kwargs)

    from langchain_openai import ChatOpenAI

    base_url = settings.ai_base_url or _DEFAULT_BASE_URLS.get(settings.ai_provider.lower())
    api_key = settings.ai_api_key
    if not api_key:
        raise RuntimeError("AI_API_KEY is required for the selected provider.")
    return ChatOpenAI(
        model=model_name,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=2,
    )


def get_llm(temperature: float = 0.2) -> BaseChatModel:
    settings = get_settings()
    logger.debug("LLM resolved: provider=%s model=%s", settings.ai_provider, settings.ai_model)
    return _get_model(settings.ai_model, temperature)


def get_fast_llm(temperature: float = 0.0) -> BaseChatModel:
    settings = get_settings()
    model_name = settings.ai_fast_model or settings.ai_model
    return _get_model(model_name, temperature)
