import os

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.tts.base import (
    TTSProvider,
    cleanup,
    play_audio_file,
    sanitize_for_speech,
    stop_speaking,
)
from app.voice.tts.edge import EdgeTTS
from app.voice.tts.sarvam import SarvamTTS

logger = get_logger("tts")


def build_tts_chain() -> list[TTSProvider]:
    settings = get_settings()
    chain: list[TTSProvider] = []
    if settings.tts_provider == "sarvam":
        sarvam = SarvamTTS()
        if sarvam.available:
            chain.append(sarvam)
    chain.append(EdgeTTS())
    return chain


async def speak_text(text: str, language: str = "English") -> bool:
    """Sanitizes, synthesizes and plays text. Returns False when interrupted."""
    from app.voice.tts.base import reset_stop_flag

    speech = sanitize_for_speech(text)
    if not speech:
        return True

    reset_stop_flag()
    last_error: Exception | None = None
    for provider in build_tts_chain():
        path = None
        try:
            logger.info("TTS via %s (%s): %s", provider.name, language, speech[:60])
            path = await provider.synthesize(speech, language)
            completed = await play_audio_file(path)
            return completed
        except Exception as exc:
            logger.warning("TTS provider %s failed: %s", provider.name, exc)
            last_error = exc
        finally:
            if path:
                cleanup(path)

    logger.error("All TTS providers failed: %s", last_error)
    return False


__all__ = ["speak_text", "stop_speaking"]
