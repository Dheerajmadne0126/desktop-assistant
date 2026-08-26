import asyncio

from app.core.logging import get_logger
from app.voice.tts.base import EDGE_VOICES, TTSProvider, cleanup, make_temp_audio

logger = get_logger("tts.edge")


class EdgeTTS(TTSProvider):
    name = "edge"

    async def synthesize(self, text: str, language: str) -> str:
        import edge_tts

        voice = EDGE_VOICES.get(language, EDGE_VOICES["English"])
        out_path = make_temp_audio(".mp3")
        communicate = edge_tts.Communicate(text, voice, rate="+10%")
        try:
            await asyncio.wait_for(communicate.save(out_path), timeout=30)
        except Exception:
            cleanup(out_path)
            raise
        return out_path
