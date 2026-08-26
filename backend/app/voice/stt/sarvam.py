import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.stt.base import STTProvider, STTResult

logger = get_logger("stt.sarvam")

URL = "https://api.sarvam.ai/speech-to-text"


class SarvamSTT(STTProvider):
    name = "sarvam"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.sarvam_api_key
        self.model = settings.sarvam_stt_model

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def transcribe(self, wav_bytes: bytes, sample_rate: int = 16000) -> STTResult:
        if not self.available:
            raise RuntimeError("SARVAM_API_KEY not configured")

        headers = {"api-subscription-key": self.api_key}
        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {"model": self.model, "mode": "transcribe"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(URL, headers=headers, files=files, data=data)

        if response.status_code != 200:
            raise RuntimeError(f"Sarvam STT HTTP {response.status_code}: {response.text[:200]}")

        payload = response.json()
        text = (payload.get("transcript") or "").strip()
        language = payload.get("language_code", "unknown")
        probability = payload.get("language_probability")
        confidence = float(probability) if isinstance(probability, (int, float)) else None
        return STTResult(text=text, language=language, provider=self.name, confidence=confidence)
