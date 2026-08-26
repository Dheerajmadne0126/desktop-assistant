import time

import pytest

from app.voice.mic import MicrophoneHub
from app.voice.pipeline import is_sleep_command
from app.voice.vad import EnergyVAD, PhraseRecorder, compute_rms


def test_hub_fanout_and_suppression():
    hub = MicrophoneHub()
    block = b"\x01\x02" * 10

    hub._on_audio(block, 0, None, None)
    assert hub.wake_q.qsize() == 1
    assert hub.capture_q.qsize() == 1

    hub.suppress_wake(True)
    hub._on_audio(block, 0, None, None)
    assert hub.wake_q.qsize() == 0
    assert hub.capture_q.qsize() == 2

    hub.suppress_wake(False)
    hub.set_capture(False)
    hub._on_audio(block, 0, None, None)
    assert hub.wake_q.qsize() == 1


@pytest.mark.parametrize(
    "text,expected",
    [
        ("stop listening", True),
        ("go to sleep", True),
        ("Sleep Jarvis", True),
        ("deactivate", True),
        ("सो जा", True),
        ("bas", True),
        ("stop", True),
        ("open chrome", False),
        ("what is my name", False),
        ("search node jobs", False),
    ],
)
def test_sleep_command_matcher(text, expected):
    assert is_sleep_command(text) is expected


def test_vad_threshold_tracks_noise_floor():
    vad = EnergyVAD()
    quiet = b"\x00\x00" * 1280
    for _ in range(30):
        vad.observe_idle(quiet)
    assert vad.threshold >= 480

    loud = b"\x50\x05" * 1280
    assert vad.process(loud) is True


def _block(amplitude: int) -> bytes:
    return amplitude.to_bytes(2, "little") * 1280


@pytest.mark.asyncio
async def test_collector_captures_with_warm_preroll():
    hub = MicrophoneHub()
    recorder = PhraseRecorder(hub)
    recorder.start_worker()

    import asyncio
    import threading

    def feeder():
        for i in range(40):
            amp = 3000 if 4 <= i < 14 else 1
            hub.capture_q.put(_block(amp))
            time.sleep(0.01)

    async def run():
        feeder_thread = threading.Thread(target=feeder)
        getter = asyncio.to_thread(recorder.record_phrase, timeout=6)

        await asyncio.sleep(0.05)
        feeder_thread.start()
        return await getter

    wav = await run()
    from app.voice.vad import compute_rms as _rms
    print("DBG thread_alive=", recorder.thread.is_alive(), "capture=", recorder.hub.capture_enabled, "qsize=", recorder.hub.capture_q.qsize(), "resultq=", recorder._result_q.qsize())

    assert wav is not None, "collector failed to produce WAV"
    assert compute_rms(wav[:4000]) > 100 or compute_rms(wav[4000:8000]) > 100
    recorder.stop_worker()

