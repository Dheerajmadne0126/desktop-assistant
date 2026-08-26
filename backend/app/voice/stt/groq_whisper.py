import io

from app.core.config import get_settings
from app.voice.stt.base import STTProvider, STTResult


class GroqWhisperSTT(STTProvider):
    name = "groq_whisper"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.groq_api_key
        self.model = "whisper-large-v3-turbo"

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def transcribe(self, wav_bytes: bytes, sample_rate: int = 16000) -> STTResult:
        import asyncio

        if not self.available:
            raise RuntimeError("GROQ_API_KEY not configured")
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, self._sync_transcribe, wav_bytes)
        return STTResult(text=text.strip(), language="unknown", provider=self.name)

    def _sync_transcribe(self, wav_bytes: bytes) -> str:
        from groq import Groq

        client = Groq(api_key=get_settings().groq_api_key)
        buffer = io.BytesIO(wav_bytes)
        buffer.name = "audio.wav"
        transcription = client.audio.transcriptions.create(
            model=self.model,
            file=buffer,
            response_format="text",
        )
        return str(transcription)
