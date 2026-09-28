import base64
import asyncio

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.tts.base import (
    SARVAM_LANG_CODES,
    TTSProvider,
)

logger = get_logger("tts.sarvam")

URL = "https://api.sarvam.ai/text-to-speech"


class SarvamTTS(TTSProvider):
    name = "sarvam"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.sarvam_api_key
        self.model = settings.sarvam_tts_model
        
        voice_pref = (settings.tts_voice or settings.sarvam_tts_speaker).lower()
        if voice_pref == "female":
            self.speaker = "priya"
        elif voice_pref == "male":
            self.speaker = "amartya"
        else:
            self.speaker = settings.tts_voice or settings.sarvam_tts_speaker

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def synthesize(self, text: str, language: str) -> bytes:
        if not self.available:
            raise RuntimeError("SARVAM_API_KEY not configured")

        lang_code = SARVAM_LANG_CODES.get(language, "en-IN")
        payload = {
            "inputs": [text],
            "target_language_code": lang_code,
            "speaker": self.speaker,
            "pace": 1.05,
            "speech_sample_rate": get_settings().tts_sample_rate,
            "enable_preprocessing": True,
            "model": self.model,
        }
        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(URL, json=payload, headers=headers)

        if response.status_code != 200:
            raise RuntimeError(f"Sarvam TTS HTTP {response.status_code}: {response.text[:200]}")

        audios = response.json().get("audios") or []
        if not audios:
            raise RuntimeError("Sarvam TTS returned no audio")

        return base64.b64decode(audios[0])
