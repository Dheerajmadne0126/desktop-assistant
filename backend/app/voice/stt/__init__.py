import time

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.stt.base import STTProvider, STTResult
from app.voice.stt.google_free import GoogleFreeSTT
from app.voice.stt.groq_whisper import GroqWhisperSTT
from app.voice.stt.local_whisper import LocalWhisperSTT
from app.voice.stt.sarvam import SarvamSTT

logger = get_logger("stt")

_cloud_down_until = 0.0
_CLOUD_OUTAGE_SECONDS = 90

# 'ok' | 'audio' | 'network' — describes why the last call returned None
last_failure_kind = "ok"

_NETWORK_MARKERS = (
    "getaddrinfo",
    "connection",
    "timed out",
    "temporarily unavailable",
    "network is unreachable",
    "name or service not known",
)


def _is_network_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _NETWORK_MARKERS)


def build_stt_chain() -> list[STTProvider]:
    settings = get_settings()
    providers: list[STTProvider] = []

    cloud_down = time.time() < _cloud_down_until

    preferred = settings.stt_provider.lower()
    if not cloud_down:
        if preferred == "sarvam":
            sarvam = SarvamSTT()
            if sarvam.available:
                providers.append(sarvam)
        elif preferred == "groq_whisper":
            groq = GroqWhisperSTT()
            if groq.available:
                providers.append(groq)

        providers.append(GoogleFreeSTT(language="mr-IN"))
        providers.append(GoogleFreeSTT(language="en-IN"))

        if preferred != "groq_whisper" and settings.groq_api_key:
            groq = GroqWhisperSTT()
            if groq.available:
                providers.append(groq)

    local = LocalWhisperSTT()
    if local.available:
        providers.append(local)

    if cloud_down:
        logger.debug("Cloud STT skipped (outage window active); using local only.")

    return providers


def mark_cloud_outage() -> None:
    global _cloud_down_until
    _cloud_down_until = time.time() + _CLOUD_OUTAGE_SECONDS


async def transcribe_with_fallback(
    wav_bytes: bytes, sample_rate: int = 16000, chain: list[STTProvider] | None = None
) -> STTResult | None:
    """Returns STTResult, or None when every provider failed (caller should notify)."""
    global last_failure_kind

    providers = chain if chain is not None else build_stt_chain()
    if not providers:
        last_failure_kind = "audio"
        return None

    errors: list[str] = []
    network_seen = False
    for provider in providers:
        try:
            result = await provider.transcribe(wav_bytes, sample_rate)
            if result.text:
                logger.info(
                    "STT via %s (%s): %s",
                    provider.name,
                    result.language,
                    result.text[:80],
                )
                last_failure_kind = "ok"
                return result
        except Exception as exc:
            logger.warning("STT provider %s failed: %s", provider.name, exc)
            errors.append(f"{provider.name}: {exc}")
            if provider.name in ("sarvam", "google_free", "groq_whisper") and _is_network_error(exc):
                network_seen = True
                mark_cloud_outage()

    last_failure_kind = "network" if network_seen else "audio"
    if errors:
        logger.error("All STT providers failed: %s", "; ".join(errors[:4]))
    return None


__all__ = ["STTResult", "build_stt_chain", "transcribe_with_fallback"]
