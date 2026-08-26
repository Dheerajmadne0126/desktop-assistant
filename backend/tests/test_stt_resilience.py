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
