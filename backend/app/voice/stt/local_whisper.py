import asyncio
import io
import logging
import tempfile
import threading
import wave
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.stt.base import STTProvider, STTResult

logger = get_logger("stt.local")

try:
    from faster_whisper import WhisperModel  # noqa: F401

    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False

# huggingface_hub warns about unauthenticated requests every time the cached
# model is touched ("Please set a HF_TOKEN..."). The model is downloaded once
# and used offline afterwards, so silence that noise.
logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)


class LocalWhisperSTT(STTProvider):
    """Fully offline fallback via faster-whisper. Used when cloud STT is unreachable."""

    name = "local_whisper"
    
    # Singleton instance
    _instance: Optional["LocalWhisperSTT"] = None
    _init_lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure model is loaded only once."""
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._model = None
        self._lock = threading.Lock()
        self._initialized = True

    @property
    def available(self) -> bool:
        return FASTER_WHISPER_AVAILABLE

    def _ensure_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    settings = get_settings()
                    size = getattr(settings, "local_stt_model", "base")
                    logger.info("Loading offline Whisper '%s' (first time may download)…", size)
                    self._model = WhisperModel(
                        size, device="cpu", compute_type="int8"
                    )
        return self._model

    async def transcribe(self, wav_bytes: bytes, sample_rate: int = 16000) -> STTResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_transcribe, wav_bytes)

    def _sync_transcribe(self, wav_bytes: bytes) -> STTResult:
        model = self._ensure_model()
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            tmp.write(wav_bytes)
            tmp.close()
            segments, info = model.transcribe(
                tmp.name,
                beam_size=2,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            parts = [seg.text.strip() for seg in segments]
            text = " ".join(p for p in parts if p)
            lang = info.language or "unknown"
            logger.info("Local whisper heard (%s): %s", lang, text[:60])
            return STTResult(text=text, language=lang, provider=self.name)
        finally:
            import os

            try:
                os.unlink(tmp.name)
            except OSError:
                pass
