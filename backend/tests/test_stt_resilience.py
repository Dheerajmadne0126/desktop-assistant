import asyncio

import pytest

from app.voice import stt as stt_module
from app.voice.stt.base import STTProvider, STTResult
from app.voice.stt import transcribe_with_fallback


class FakeProvider(STTProvider):
    def __init__(self, name, text=None, exc=None):
        self.name = name
        self._text = text
        self._exc = exc

    async def transcribe(self, wav_bytes, sample_rate=16000):
        if self._exc:
            raise self._exc(self._text or "boom")
        return STTResult(text=self._text or "", language="en", provider=self.name)


@pytest.mark.asyncio
async def test_network_failure_kind():
    chain = [FakeProvider("sarvam", exc=ConnectionError("getaddrinfo failed"))]
    assert await transcribe_with_fallback(b"x", chain=chain) is None
    assert stt_module.last_failure_kind == "network"


@pytest.mark.asyncio
async def test_audio_garbage_kind():
    chain = [FakeProvider("google_free"), FakeProvider("google_free")]
    assert await transcribe_with_fallback(b"x", chain=chain) is None
    assert stt_module.last_failure_kind == "audio"


@pytest.mark.asyncio
async def test_success_resets_kind():
    chain = [FakeProvider("sarvam", text="hello there")]
    result = await transcribe_with_fallback(b"x", chain=chain)
    assert result is not None
    assert stt_module.last_failure_kind == "ok"


class SlowProvider(STTProvider):
    def __init__(self, name, delay, text):
        self.name = name
        self._delay = delay
        self._text = text

    async def transcribe(self, wav_bytes, sample_rate=16000):
        await asyncio.sleep(self._delay)
        return STTResult(text=self._text, language="en", provider=self.name)


@pytest.mark.asyncio
async def test_cloud_providers_run_concurrently_fastest_wins():
    """A slow preferred provider must not block a fast fallback: the first
    non-empty transcript wins and the slow provider is cancelled."""
    import time

    chain = [
        SlowProvider("groq_whisper", 2.0, "slow text"),
        FakeProvider("google_free", text="fast text"),
    ]
    start = time.monotonic()
    result = await transcribe_with_fallback(b"x", chain=chain)
    elapsed = time.monotonic() - start
    assert result is not None
    assert result.provider == "google_free"
    assert result.text == "fast text"
    assert elapsed < 1.5, "waited for the slow provider instead of racing"


class HangingProvider(STTProvider):
    name = "groq_whisper"

    async def transcribe(self, wav_bytes, sample_rate=16000):
        await asyncio.sleep(10)
        return STTResult(text="late", language="en", provider=self.name)


class LocalFake(STTProvider):
    name = "local_whisper"

    async def transcribe(self, wav_bytes, sample_rate=16000):
        return STTResult(text="offline fallback", language="mr", provider=self.name)


@pytest.mark.asyncio
async def test_cloud_timeout_then_local_fallback():
    """When every cloud provider hangs, the local whisper model still runs."""
    chain = [HangingProvider(), LocalFake()]
    result = await transcribe_with_fallback(b"x", chain=chain)
    assert result is not None
    assert result.provider == "local_whisper"
    assert result.text == "offline fallback"
