import queue
import threading

from app.core.logging import get_logger

logger = get_logger("mic")


class MicrophoneHub:
    """SINGLE owner of the microphone.

    One continuous RawInputStream fans every block out to two consumers:
      - wake_q   : wake-word reader (suppressed while JARVIS speaks)
      - capture_q: recorder / barge-in monitor (gated by capture_enabled)

    The stream is opened once and never reopened per utterance.
    """

    def __init__(self, sample_rate: int = 16000, chunk_samples: int = 1280) -> None:
        self.sample_rate = sample_rate
        self.chunk_samples = chunk_samples
        self.wake_q: "queue.Queue[bytes]" = queue.Queue(maxsize=250)
        self.capture_q: "queue.Queue[bytes]" = queue.Queue(maxsize=500)

        self._wake_suppressed = threading.Event()
        self._capture_enabled = threading.Event()
        self._stopped = threading.Event()
        self._stream = None

    @property
    def block_bytes(self) -> int:
        return self.chunk_samples * 2

    def start(self) -> bool:
        if self._stream is not None:
            return True
        try:
            import sounddevice as sd

            opened = {}

            def _open():
                stream = sd.RawInputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.chunk_samples,
                    dtype="int16",
                    channels=1,
                    callback=self._on_audio,
                )
                stream.start()
                opened["stream"] = stream

            opener = threading.Thread(target=_open, name="mic-open", daemon=True)
            opener.start()
            opener.join(timeout=8)

            if opener.is_alive():
                logger.error(
                    "Microphone open timed out after 8s "
                    "(device busy or locked by another process?). "
                    "Voice input disabled for this run."
                )
                return False

            self._stream = opened.get("stream")
            if self._stream is None:
                return False
            logger.info(
                "MicrophoneHub stream live (%d Hz, %d-sample blocks).",
                self.sample_rate,
                self.chunk_samples,
            )
            return True
        except Exception as exc:
            logger.error("Microphone open failed: %s", exc)
            self._stream = None
            return False

    def _on_audio(self, indata, frames, time_info, status) -> None:
        data = bytes(indata)
        if not self._stopped.is_set():
            try:
                self.capture_q.put_nowait(data)
            except queue.Full:
                pass
        if not self._wake_suppressed.is_set():
            try:
                self.wake_q.put_nowait(data)
            except queue.Full:
                pass

    def suppress_wake(self, suppressed: bool) -> None:
        if suppressed:
            self._wake_suppressed.set()
            try:
                while True:
                    self.wake_q.get_nowait()
            except queue.Empty:
                pass
        else:
            self._wake_suppressed.clear()

    def set_capture(self, enabled: bool) -> None:
        if enabled:
            self._capture_enabled.set()
        else:
            self._capture_enabled.clear()

    @property
    def capture_enabled(self) -> bool:
        return self._capture_enabled.is_set()

    def stop(self) -> None:
        self._stopped.set()
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        except Exception:
            pass
        self._stream = None
