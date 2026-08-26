import audioop
import io
import queue
import threading
import time
import wave
from collections import deque

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.mic import MicrophoneHub

logger = get_logger("vad")

CHUNK_SAMPLES = 1280


def compute_rms(pcm_bytes: bytes) -> float:
    if not pcm_bytes:
        return 0.0
    try:
        return float(audioop.rms(pcm_bytes, 2))
    except Exception:
        return 0.0


class EnergyVAD:
    """Live noise-floor tracking with hysteresis. No manual calibration steps."""

    def __init__(self, factor_above_noise: float = 2.4, floor: int = 320) -> None:
        self.noise_floor = float(floor)
        self.factor = factor_above_noise
        self.speech_active = False

    @property
    def threshold(self) -> float:
        return max(self.noise_floor * self.factor, 480)

    def observe_idle(self, pcm_block: bytes) -> None:
        """Learns ambient noise ONLY from quiet blocks — never from speech or
        TTS bleed, otherwise the threshold rises until JARVIS goes deaf."""
        rms = compute_rms(pcm_block)
        if rms < self.threshold * 0.8:
            self.noise_floor = self.noise_floor * 0.95 + rms * 0.05

    def process(self, pcm_block: bytes) -> bool:
        rms = compute_rms(pcm_block)
        if self.speech_active:
            if rms < self.threshold * 0.7:
                self.speech_active = False
        else:
            if rms > self.threshold:
                self.speech_active = True
        return self.speech_active


class PhraseRecorder:
    """Continuous capture worker on the shared stream.

    - Preroll ring buffer is ALWAYS warm -> speech onset is never clipped.
    - Noise floor updates continuously while idle -> no per-turn calibration.
    - While capture is disabled but barge-in monitor is armed, loud sustained
      mic energy triggers the on_barge_in callback (user interrupting TTS).
    """

    def __init__(self, hub: MicrophoneHub) -> None:
        settings = get_settings()
        self.hub = hub
        self.sample_rate = settings.sample_rate
        self.chunk = CHUNK_SAMPLES
        self.silence_limit_s = settings.phrase_silence_ms / 1000
        self.max_seconds = settings.phrase_max_seconds
        self.preroll_s = settings.phrase_preroll_ms / 1000
        self.vad = EnergyVAD()

        chunks_per_second = self.sample_rate / self.chunk
        self._preroll_chunks = max(2, int(self.preroll_s * chunks_per_second))
        self._preroll: deque = deque(maxlen=self._preroll_chunks)
        self._min_speech_chunks = max(1, int(0.20 * chunks_per_second))

        self._barge_callback = None
        self._barge_armed = threading.Event()
        self._capture_requested = threading.Event()
        self._result_q: "queue.Queue" = queue.Queue(maxsize=4)
        self._stopped = threading.Event()
        self.thread: threading.Thread | None = None

    def set_barge_monitor(self, callback, armed: bool) -> None:
        self._barge_callback = callback
        if armed:
            self._barge_armed.set()
        else:
            self._barge_armed.clear()

    def start_worker(self) -> None:
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self._loop, name="jarvis-capture", daemon=True)
        self.thread.start()
        logger.info("Capture worker started (warm preroll %dms).", int(self.preroll_s * 1000))

    def stop_worker(self) -> None:
        self._stopped.set()

    def record_phrase(self, timeout: float | None = None) -> bytes | None:
        self._preroll.clear()
        self.vad.speech_active = False
        self.hub.set_capture(True)
        try:
            timeout = timeout or (self.max_seconds + 3)
            return self._result_q.get(timeout=timeout)
        except queue.Empty:
            return None
        finally:
            self.hub.set_capture(False)

    def _loop(self) -> None:
        block_bytes = self.chunk * 2
        chunks_per_second = self.sample_rate / self.chunk
        silence_chunks_limit = max(1, int(self.silence_limit_s * chunks_per_second))

        preroll: deque = deque(maxlen=self._preroll_chunks)
        capturing = False
        collected: list[bytes] = []
        speech_chunks = 0
        silence_chunks = 0
        max_capture_chunks = int(self.max_seconds * chunks_per_second)
        barge_hits = 0
        last_block_at = time.monotonic()

        while not self._stopped.is_set():
            try:
                block = self.hub.capture_q.get(timeout=0.25)
                last_block_at = time.monotonic()
            except queue.Empty:
                if capturing and (time.monotonic() - last_block_at) > 1.0:
                    wav = self._to_wav(collected) if speech_chunks >= self._min_speech_chunks else None
                    capturing = False
                    collected = []
                    logger.debug("Capture finalized after stream stall.")
                    self._emit(wav)
                continue

            requested = self.hub.capture_enabled

            if not capturing and not requested and not self._barge_armed.is_set():
                self.vad.observe_idle(block)
                if len(preroll) == preroll.maxlen:
                    preroll.popleft()
                preroll.append(block)
                continue

            rms = compute_rms(block)

            if not capturing and not requested and self._barge_armed.is_set():
                threshold_barge = max(self.vad.threshold * 1.8, 1400)
                if rms > threshold_barge:
                    barge_hits += 1
                else:
                    barge_hits = 0
                if barge_hits >= 4 and self._barge_callback is not None:
                    barge_hits = 0
                    cb = self._barge_callback
                    self._barge_armed.clear()
                    threading.Thread(target=cb, daemon=True).start()
                if len(preroll) == preroll.maxlen:
                    preroll.popleft()
                preroll.append(block)
                self.vad.observe_idle(block)
                continue

            if not capturing and requested:
                capturing = True
                speech_chunks = 0
                silence_chunks = 0
                preroll.clear()
                collected = list(preroll)
                logger.debug("Capture started.")

            if capturing:
                collected.append(block)
                voiced = self.vad.process(block)
                if voiced:
                    speech_chunks += 1
                    silence_chunks = 0
                else:
                    silence_chunks += 1

                finished = (
                    (speech_chunks >= self._min_speech_chunks and silence_chunks >= silence_chunks_limit)
                    or len(collected) >= max_capture_chunks
                )
                if finished:
                    wav = self._to_wav(collected)
                    collected = []
                    capturing = False
                    if speech_chunks < self._min_speech_chunks:
                        logger.debug("Captured audio below minimum speech; discarded.")
                        self._emit(None)
                    else:
                        self._emit(wav)
            else:
                if len(preroll) == preroll.maxlen:
                    preroll.popleft()
                preroll.append(block)
                self.vad.observe_idle(block)

    def _emit(self, payload):
        try:
            self._result_q.put_nowait(payload)
        except queue.Full:
            pass

    def _to_wav(self, chunks: list[bytes]) -> bytes | None:
        buffer = io.BytesIO()
        try:
            with wave.open(buffer, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(self.sample_rate)
                for c in chunks:
                    wav.writeframes(c)
            return buffer.getvalue()
        except Exception as exc:
            logger.warning("WAV encode failed: %s", exc)
            return None
