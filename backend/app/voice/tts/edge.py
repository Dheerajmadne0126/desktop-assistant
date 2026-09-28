import asyncio

from app.core.logging import get_logger
from app.voice.tts.base import EDGE_VOICES_MALE, EDGE_VOICES_FEMALE, TTSProvider, play_audio_stream
from app.core.config import get_settings

logger = get_logger("tts.edge")


class EdgeTTS(TTSProvider):
    name = "edge"

    async def synthesize(self, text: str, language: str) -> bytes:
        import edge_tts

        settings = get_settings()
        voice_pref = (settings.tts_voice or "").lower()
        if voice_pref in ("female", "priya", "swara", "aarohi", "neerja", "meera"):
            voices = EDGE_VOICES_FEMALE
        else:
            voices = EDGE_VOICES_MALE

        voice = voices.get(language, voices["English"])
        # Use faster rate for more responsive TTS
        communicate = edge_tts.Communicate(text, voice, rate="+25%")
        audio_data = bytearray()
        try:
            async for msg in communicate.stream():
                if msg["type"] == "audio":
                    audio_data.extend(msg["data"])
        except Exception:
            raise
        return bytes(audio_data)

    async def synthesize_stream(self, text: str, language: str):
        """Yields audio chunks as they're generated for true streaming playback."""
        import edge_tts

        settings = get_settings()
        voice_pref = (settings.tts_voice or "").lower()
        if voice_pref in ("female", "priya", "swara", "aarohi", "neerja", "meera"):
            voices = EDGE_VOICES_FEMALE
        else:
            voices = EDGE_VOICES_MALE

        voice = voices.get(language, voices["English"])
        # Use faster rate for streaming too
        communicate = edge_tts.Communicate(text, voice, rate="+25%")
        try:
            async for msg in communicate.stream():
                if msg["type"] == "audio":
                    yield msg["data"]
        except Exception:
            raise