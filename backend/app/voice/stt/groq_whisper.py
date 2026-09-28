import io

from app.core.config import get_settings
from app.voice.stt.base import STTProvider, STTResult
from app.voice.stt.clients import get_groq_client

class GroqWhisperSTT(STTProvider):
    name = "groq_whisper"

    def __init__(self, language: str = "mr") -> None:
        settings = get_settings()
        self.language = language
        self.model = "whisper-large-v3-turbo"

    @property
    def available(self) -> bool:
        settings = get_settings()
        api_key = settings.groq_api_key
        if not api_key and settings.ai_provider.lower() == "groq":
            api_key = settings.ai_api_key
        return bool(api_key)

    async def transcribe(self, wav_bytes: bytes, sample_rate: int = 16000) -> STTResult:
        import asyncio

        if not self.available:
            raise RuntimeError("GROQ_API_KEY not configured")
        
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, self._sync_transcribe, wav_bytes)
        return STTResult(text=text.strip(), language=self.language, provider=self.name)

    def _sync_transcribe(self, wav_bytes: bytes) -> str:
        client = get_groq_client()

        buffer = io.BytesIO(wav_bytes)
        buffer.name = "audio.wav"
        
        # Use explicit language to prevent hallucination
        # Only use auto-detection if explicitly requested
        lang_param = self.language
        if self.language == "auto":
            lang_param = None
        
        kwargs = {
            "model": self.model,
            "file": buffer,
            "response_format": "verbose_json",
            "prompt": "Jarvis, assistant, Hindi, Marathi, English, command, open, close, play, search, time, weather, email, browser, app",
        }
        if lang_param:
            kwargs["language"] = lang_param
            
        transcription = client.audio.transcriptions.create(**kwargs)
        
        detected_lang = getattr(transcription, "language", "")
        text = getattr(transcription, "text", "")
        
        # If it auto-detected a language other than Marathi, Hindi, or English, it's likely a short-audio hallucination
        # Only check if we didn't explicitly set a language
        if (not self.language or self.language == "auto") and detected_lang not in ["mr", "hi", "en", "en-US", "en-GB", "english", "marathi", "hindi"]:
            raise RuntimeError(f"Groq Whisper hallucinated weird language: {detected_lang}")
            
        return text