import asyncio
import io
import os
import re
import threading
from abc import ABC, abstractmethod

import pygame

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("tts")

_stop_event = threading.Event()
_mixer_ready = False
_MIXER_SAMPLE_RATE = 22050  # Fixed sample rate for all TTS output

EDGE_VOICES_MALE = {
    "Marathi": "mr-IN-ManoharNeural",
    "Hindi": "hi-IN-MadhurNeural",
    "English": "en-IN-PrabhatNeural",
    "unknown": "en-IN-PrabhatNeural",
}

EDGE_VOICES_FEMALE = {
    "Marathi": "mr-IN-AarohiNeural",
    "Hindi": "hi-IN-SwaraNeural",
    "English": "en-IN-NeerjaNeural",
    "unknown": "en-IN-NeerjaNeural",
}

SARVAM_LANG_CODES = {
    "Marathi": "mr-IN",
    "Hindi": "hi-IN",
    "English": "en-IN",
    "unknown": "en-IN",
}

_MARKDOWN_RE = re.compile(r"[*_`#>\[\]()~|]")
_URL_RE = re.compile(r"https?://\S+")
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002700-\U000027BF\U0001F000-\U0001F02F"
    "\U00002600-\U000026FF\U0001F900-\U0001F9FF\uFE0F]"
)
_MULTI_SPACE_RE = re.compile(r" {2,}")


def sanitize_for_speech(text: str) -> str:
    cleaned = _URL_RE.sub(" link ", text or "")
    cleaned = _MARKDOWN_RE.sub(" ", cleaned)
    cleaned = _EMOJI_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s*\n\s*", ". ", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    return cleaned.strip(" .,-")[:1200]


def _ensure_mixer_at_rate(sample_rate: int) -> bool:
    """Ensure mixer is initialized at the specified sample rate."""
    global _mixer_ready, _MIXER_SAMPLE_RATE
    try:
        current = pygame.mixer.get_init()
        if current and current[0] == sample_rate:
            _mixer_ready = True
            _MIXER_SAMPLE_RATE = sample_rate
            return True
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        pygame.mixer.init(frequency=sample_rate)
        _mixer_ready = True
        _MIXER_SAMPLE_RATE = sample_rate
        logger.info("[AUDIO] mixer initialized at %dHz.", sample_rate)
        return True
    except Exception as exc:
        logger.warning("Mixer init failed: %s", exc)
        return False


def prepare_output_mixer(sample_rate: int) -> bool:
    """Pre-opens the mixer at the TTS sample rate so per-utterance re-inits vanish."""
    return _ensure_mixer_at_rate(sample_rate)


def stop_speaking() -> None:
    _stop_event.set()
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass


def reset_stop_flag() -> None:
    _stop_event.clear()


async def play_audio_file(audio_bytes: bytes, poll_interval: float = 0.05) -> bool:
    """Plays audio bytes directly from memory, returns False when cancelled via stop_speaking()."""
    import wave

    loop = asyncio.get_running_loop()

    def _start():
        if not _ensure_mixer_at_rate(_MIXER_SAMPLE_RATE):
            raise RuntimeError("No audio output device")

        expected_length = 0.0
        # Check if it's a WAV to get duration
        try:
            with wave.open(io.BytesIO(audio_bytes), "rb") as w:
                rate = w.getframerate()
                frames = w.getnframes()
                expected_length = frames / float(rate)
        except Exception as exc:
            logger.debug("[AUDIO] wav pre-read skipped (likely mp3): %s", exc)

        pygame.mixer.music.load(io.BytesIO(audio_bytes))

        if expected_length <= 0.0:
            try:
                expected_length = pygame.mixer.Sound(io.BytesIO(audio_bytes)).get_length()
            except Exception as exc:
                logger.debug("[AUDIO] length probe skipped: %s", exc)

        logger.info(
            "[AUDIO] output=%dHz expected=%.1fs",
            _MIXER_SAMPLE_RATE,
            expected_length,
        )
        pygame.mixer.music.play()
        return expected_length

    expected_length = await loop.run_in_executor(None, _start)

    started_at = asyncio.get_running_loop().time()
    while pygame.mixer.music.get_busy():
        if _stop_event.is_set():
            return False
        await asyncio.sleep(poll_interval)

    played = asyncio.get_running_loop().time() - started_at
    if expected_length > 0.5 and played < expected_length * 0.25:
        logger.warning(
            "[AUDIO] playback finished in %.1fs but file is %.1fs — "
            "output device is rendering silence. Check speakers/volume/"
            "default output device.",
            played,
            expected_length,
        )
    return True


async def play_audio_stream(audio_chunk_iterator, poll_interval: float = 0.05) -> bool:
    """Plays audio from an async iterator of chunks. For true streaming TTS.
    
    This queues chunks and plays them sequentially, starting playback as soon
    as the first chunk is available.
    """
    import wave
    import tempfile

    loop = asyncio.get_running_loop()
    
    # Collect all chunks to a temporary file, then play
    # This is a workaround since pygame.mixer.music doesn't support streaming
    # For true streaming, we'd need to use pygame.mixer.Sound or a different audio library
    chunks = []
    async for chunk in audio_chunk_iterator:
        chunks.append(chunk)
    
    if not chunks:
        return True
    
    audio_bytes = b"".join(chunks)
    return await play_audio_file(audio_bytes, poll_interval)


class TTSProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def synthesize(self, text: str, language: str) -> bytes:
        """Returns raw audio bytes."""

    async def synthesize_stream(self, text: str, language: str):
        """Optional: yields audio chunks for streaming playback.
        
        Default implementation falls back to synthesize() and yields single chunk.
        """
        audio = await self.synthesize(text, language)
        yield audio