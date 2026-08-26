import asyncio
import io
import tempfile
import threading
import wave

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.stt.base import STTProvider, STTResult

logger = get_logger("stt.local")

try:
    from faster_whisper import WhisperModel  # noqa: F401

    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False


class LocalWhisperSTT(STTProvider):
    """Fully offline fallback via faster-whisper. Used when cloud STT is unreachable."""

    name = "local_whisper"

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

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
