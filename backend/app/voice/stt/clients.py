import httpx
from groq import Groq
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("stt.clients")

_sarvam_client: httpx.AsyncClient | None = None
_groq_client: Groq | None = None
_clients_initialized = False


def get_sarvam_client() -> httpx.AsyncClient:
    global _sarvam_client, _clients_initialized
    if _sarvam_client is None:
        settings = get_settings()
        _sarvam_client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
        logger.info("Initialized shared Sarvam HTTP client")
    return _sarvam_client


def get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        settings = get_settings()
        api_key = settings.groq_api_key
        if not api_key and settings.ai_provider.lower() == "groq":
            api_key = settings.ai_api_key
        _groq_client = Groq(api_key=api_key)
        logger.info("Initialized shared Groq client")
    return _groq_client


async def close_clients() -> None:
    global _sarvam_client, _groq_client
    if _sarvam_client is not None:
        await _sarvam_client.aclose()
        _sarvam_client = None
        logger.info("Closed Sarvam HTTP client")
    if _groq_client is not None:
        _groq_client = None
        logger.info("Closed Groq client")