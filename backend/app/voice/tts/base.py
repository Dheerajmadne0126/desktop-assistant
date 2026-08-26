import asyncio
import os
import re
import tempfile
import threading
from abc import ABC, abstractmethod

import pygame

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("tts")

_stop_event = threading.Event()
_mixer_ready = False

EDGE_VOICES = {
    "Marathi": "mr-IN-ManoharNeural",
    "Hindi": "hi-IN-MadhurNeural",
    "English": "en-IN-PrabhatNeural",
    "unknown": "en-IN-PrabhatNeural",
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


def ensure_mixer() -> bool:
    global _mixer_ready
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        _mixer_ready = True
        return True
    except Exception as exc:
        logger.warning("Audio mixer unavailable: %s", exc)
        return False


def prepare_output_mixer(sample_rate: int) -> bool:
    """Pre-opens the mixer at the TTS sample rate so per-utterance re-inits vanish."""
    try:
        current = pygame.mixer.get_init()
        if current and current[0] == sample_rate:
            _mixer_ready = True
            return True
        if pygame.mixer.get_init():
            pygame.mixer.quit()
        pygame.mixer.init(frequency=sample_rate)
        _mixer_ready = True
        logger.info("[AUDIO] mixer pre-initialized at %dHz.", sample_rate)
        return True
    except Exception as exc:
        logger.warning("Mixer pre-init failed: %s", exc)
        return False


def stop_speaking() -> None:
    _stop_event.set()
    try:
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass


def reset_stop_flag() -> None:
    _stop_event.clear()


async def play_audio_file(path: str, poll_interval: float = 0.05) -> bool:
    """Plays an audio file, returns False when cancelled via stop_speaking()."""
    import wave

    loop = asyncio.get_running_loop()

    def _start():
        if not ensure_mixer():
            raise RuntimeError("No audio output device")

        expected_length = 0.0
        if path.lower().endswith(".wav"):
            try:
                with wave.open(path, "rb") as w:
                    rate = w.getframerate()
                    frames = w.getnframes()
                    expected_length = frames / float(rate)
                current_init = pygame.mixer.get_init()
                if current_init and current_init[0] != rate:
                    logger.info(
                        "[AUDIO] re-initing mixer %sHz -> %sHz to match file",
                        current_init[0],
                        rate,
                    )
                    pygame.mixer.quit()
                    pygame.mixer.init(frequency=rate)
            except Exception as exc:
                logger.debug("[AUDIO] wav pre-read skipped: %s", exc)

        pygame.mixer.music.load(path)

        if expected_length <= 0.0:
            try:
                expected_length = pygame.mixer.Sound(path).get_length()
            except Exception as exc:
                logger.debug("[AUDIO] length probe skipped: %s", exc)

        logger.info(
            "[AUDIO] output=%sHz expected=%.1fs",
            (pygame.mixer.get_init() or (0,))[0],
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


def make_temp_audio(suffix: str) -> str:
    settings = get_settings()
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="jarvis_tts_", dir=tempfile.gettempdir())
    os.close(fd)
    return path


def cleanup(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


class TTSProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def synthesize(self, text: str, language: str) -> str:
        """Returns a path to a playable audio file."""
