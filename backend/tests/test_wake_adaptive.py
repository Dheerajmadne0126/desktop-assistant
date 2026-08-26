import queue
import time

import pytest

from app.voice.wakeword.provider import WakeWordListener


class FakeModel:
    def __init__(self, scores):
        self._scores = list(scores)
        self.resets = 0

    def predict(self, audio):
        return {"hey_jarvis_v0.1": self._scores.pop(0) if self._scores else 0.0}

    def reset(self):
        self.resets += 1


class FakeHub:
    class _Q:
        def get(self, timeout=None):
            raise queue.Empty

    wake_q = _Q()


import queue


@pytest.fixture
def listener(monkeypatch):
    monkeypatch.setattr(
        "app.voice.wakeword.provider.OPENWAKEWORD_AVAILABLE", True
    )
    lw = WakeWordListener.__new__(WakeWordListener)
    lw.hub = FakeHub()
    lw.threshold = 0.40
    lw.cooldown_s = 0.0
    lw.models = ["hey_jarvis"]
    lw.model = None
    lw.thread = None
    import threading

    lw._stopped = threading.Event()
    lw._last_fire = 0.0
    lw.recent_scores = []
    lw.fire_count = 0
    from collections import deque

    lw._score_window = deque(maxlen=3)
    return lw


def _drive(listener, scores, on_wake):
    listener.model = FakeModel(scores)

    import numpy as np

    reader_loop_iterations = len(scores)
    audio = np.zeros(1280, dtype=np.int16)

    for _ in range(reader_loop_iterations):
        predictions = listener.model.predict(audio)
        best = max(predictions.values())
        listener._score_window.append(best)
        listener.recent_scores.append({"ts": 0, "score": best})
        window = list(listener._score_window)
        rising = (
            len(window) == 3
            and sum(window) / 3 > listener.threshold * 0.6
            and min(window) > listener.threshold * 0.25
        )
        now = time.monotonic()
        if (best > listener.threshold or rising) and (
            now - listener._last_fire > listener.cooldown_s
        ):
            listener._last_fire = now
            listener.fire_count += 1
            on_wake()


def test_strong_single_chunk_fires(listener):
    fires = []
    _drive(listener, [0.02, 0.03, 0.55], lambda: fires.append(1))
    assert listener.fire_count == 1


def test_adaptive_rising_pattern_fires_below_threshold(listener):
    fires = []
    _drive(listener, [0.20, 0.30, 0.34], lambda: fires.append(1))
    assert listener.fire_count == 1


def test_background_noise_never_fires(listener):
    _drive(listener, [0.02, 0.05, 0.01, 0.04, 0.02], lambda: fires.append(1))
    assert listener.fire_count == 0


def test_music_burst_does_not_fire(listener):
    _drive(listener, [0.30, 0.05, 0.30], lambda: fires.append(1))
    assert listener.fire_count == 0
