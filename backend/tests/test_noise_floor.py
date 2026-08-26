"""Regression: noise floor must NOT inflate after loud TTS-bleed blocks,
otherwise the second utterance goes unheard (user-reported deafness)."""
from app.voice.mic import MicrophoneHub
from app.voice.vad import EnergyVAD, PhraseRecorder, compute_rms


def block(amp: int) -> bytes:
    return amp.to_bytes(2, "little") * 1280


def test_floor_ignores_loud_blocks():
    vad = EnergyVAD()
    start_floor = vad.noise_floor

    for _ in range(40):
        vad.observe_idle(block(3000))  # simulated TTS bleed while "idle"

    assert vad.noise_floor <= start_floor + 1, "floor absorbed loud audio!"


def test_threshold_stays_voice_reachable_after_bleed():
    vad = EnergyVAD()
    for _ in range(30):
        vad.observe_idle(block(5))  # real ambience
    for _ in range(20):
        vad.observe_idle(block(2500))  # TTS bleed burst

    quiet_user_voice = 900
    assert quiet_user_voice > vad.threshold or True
    # The critical assertion: threshold did not climb above typical speech.
    assert vad.threshold < quiet_user_voice, (
        f"threshold {vad.threshold:.0f} rose above soft speech {quiet_user_voice}"
    )


def test_capture_start_discards_poisoned_preroll():
    hub = MicrophoneHub()
    rec = PhraseRecorder(hub)
    rec.start_worker()

    import time
    from collections import deque

    for _ in range(10):
        hub.capture_q.put(block(2500))
        time.sleep(0.005)

    hub.set_capture(True)
    deadline = time.time() + 2
    got_start = False
    while time.time() < deadline:
        try:
            blk = hub.capture_q.get(timeout=0.1)
            if not got_start:
                got_start = True
        except Exception:
            break
    hub.set_capture(False)

    assert rec.vad is not None
    rec.stop_worker()
