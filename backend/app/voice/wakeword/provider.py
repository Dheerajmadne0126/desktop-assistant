import queue
import re
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("wakeword")

try:
    import openwakeword
    from openwakeword.model import Model

    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False


def _resolve_model_file(name: str) -> str | None:
    candidates = []
    if name.endswith(".onnx"):
        candidates = [name]
    elif name.endswith(".tflite"):
        base = name[:-7]
        candidates = [f"{base}.onnx", f"{base}_v0.1.onnx"]
    else:
        candidates = [f"{name}.onnx", f"{name}_v0.1.onnx", name]

    models_dir = None
    if OPENWAKEWORD_AVAILABLE:
        models_dir = Path(openwakeword.__file__).parent / "resources" / "models"

    for candidate in candidates:
        direct = Path(candidate)
        if direct.exists():
            return str(direct)
        if models_dir is not None:
            packaged = models_dir / candidate
            if packaged.exists():
                return str(packaged)
    return None


class WakeWordListener:
    """Consumes blocks from the shared MicrophoneHub; never opens its own stream."""

    def __init__(self, hub) -> None:
        self.hub = hub
        settings = get_settings()
        self.threshold = settings.wake_word_threshold
        self.cooldown_s = 1.2
        self.models = settings.wake_word_model_list or ["hey_jarvis"]

        self.model = None
        self.thread: threading.Thread | None = None
        self._stopped = threading.Event()
        self._last_fire = 0.0

        self.recent_scores: list[dict] = []
        self.fire_count = 0
        self._score_window: deque = deque(maxlen=3)

        if not OPENWAKEWORD_AVAILABLE:
            logger.warning("openwakeword not installed; wake word disabled.")
            return

        try:
            resolved = []
            for raw in self.models:
                path = _resolve_model_file(raw)
                if path:
                    resolved.append(path)
                else:
                    logger.error("Wake word model '%s' not found (onnx or tflite).", raw)
            if not resolved:
                raise RuntimeError("No wake word models could be resolved.")
            self.model = Model(wakeword_models=resolved)
            logger.info(
                "Wake word models loaded: %s (threshold=%.2f)",
                [Path(p).name for p in resolved],
                self.threshold,
            )
        except Exception as exc:
            logger.error("Failed to load wake word model: %s", exc)
            self.model = None

    @property
    def available(self) -> bool:
        return self.model is not None

    def start(self, on_wake) -> bool:
        if not self.available:
            return False

        def _reader():
            last_score_log = 0.0
            while not self._stopped.is_set():
                try:
                    data = self.hub.wake_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                try:
                    audio = np.frombuffer(data, dtype=np.int16)
                    predictions = self.model.predict(audio)
                    best_name, best_score = "", 0.0
                    for model_name, score in predictions.items():
                        if score > best_score:
                            best_name, best_score = model_name, score

                    self._score_window.append(best_score)
                    now = time.monotonic()
                    self.recent_scores.append(
                        {"ts": time.time(), "score": round(float(best_score), 3)}
                    )
                    if len(self.recent_scores) > 60:
                        del self.recent_scores[: len(self.recent_scores) - 60]

                    # Adaptive rule: instant fire on a strong chunk, OR a rising
                    # pattern (mean of last 3 near-threshold) catches accents
                    # where a single chunk never crosses the line.
                    window = list(self._score_window)
                    rising = (
                        len(window) == 3
                        and sum(window) / 3 > self.threshold * 0.6
                        and min(window) > self.threshold * 0.25
                    )
                    if (best_score > self.threshold or rising) and (
                        now - self._last_fire > self.cooldown_s
                    ):
                        self._last_fire = now
                        self.fire_count += 1
                        logger.info(
                            "Wake word detected (%s=%.2f%s)",
                            Path(best_name).name,
                            best_score,
                            ", adaptive" if rising and best_score <= self.threshold else "",
                        )
                        self.model.reset()
                        try:
                            on_wake()
                        except Exception as exc:
                            logger.error("Wake callback error: %s", exc)
                        continue

                    if (
                        0.02 < best_score <= self.threshold
                        and now - last_score_log > 3.0
                    ):
                        last_score_log = now
                        logger.info(
                            "Wake word listening: %s=%.2f (need %.2f)",
                            Path(best_name).name if best_name else "?",
                            best_score,
                            self.threshold,
                        )
                except Exception as exc:
                    logger.warning("Wake word processing error: %s", exc)

        self.thread = threading.Thread(target=_reader, name="jarvis-wakeword", daemon=True)
        self.thread.start()
        logger.info("Wake word reader started on shared stream.")
        return True

    def suppress(self, suppressed: bool) -> None:
        self.hub.suppress_wake(suppressed)

    def stop(self) -> None:
        self._stopped.set()
