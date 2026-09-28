import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.stt.base import STTProvider, STTResult
from app.voice.stt.google_free import GoogleFreeSTT
from app.voice.stt.groq_whisper import GroqWhisperSTT
from app.voice.stt.local_whisper import LocalWhisperSTT
from app.voice.stt.sarvam import SarvamSTT

logger = get_logger("stt")

_cloud_down_until = 0.0
_CLOUD_OUTAGE_SECONDS = 90

# 'ok' | 'audio' | 'network' — describes why the last call returned None
last_failure_kind = "ok"

_NETWORK_MARKERS = (
    "getaddrinfo",
    "connection",
    "timed out",
    "temporarily unavailable",
    "network is unreachable",
    "name or service not known",
)


def _is_network_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _NETWORK_MARKERS)


@dataclass
class STTRequest:
    """Track an in-flight STT request to handle race conditions."""
    request_id: str
    wav_bytes: bytes
    sample_rate: int
    created_at: float
    task: Optional[asyncio.Task] = None
    cancelled: bool = False


class STTRequestTracker:
    """Track in-flight STT requests to handle race conditions and stale results."""

    def __init__(self):
        self._current_request: Optional[STTRequest] = None
        self._lock = asyncio.Lock()

    async def start_request(self, wav_bytes: bytes, sample_rate: int) -> str:
        """Start a new STT request, cancelling any previous one."""
        async with self._lock:
            # Cancel previous request if still running
            if self._current_request and self._current_request.task:
                self._current_request.cancelled = True
                self._current_request.task.cancel()
                try:
                    await self._current_request.task
                except asyncio.CancelledError:
                    pass

            request_id = uuid.uuid4().hex[:8]
            self._current_request = STTRequest(
                request_id=request_id,
                wav_bytes=wav_bytes,
                sample_rate=sample_rate,
                created_at=time.time(),
            )
            return request_id

    async def set_task(self, request_id: str, task: asyncio.Task) -> None:
        """Set the task for a request."""
        async with self._lock:
            if self._current_request and self._current_request.request_id == request_id:
                self._current_request.task = task

    async def is_current(self, request_id: str) -> bool:
        """Check if a request ID is still the current one."""
        async with self._lock:
            return (
                self._current_request is not None
                and self._current_request.request_id == request_id
                and not self._current_request.cancelled
            )

    async def complete_request(self, request_id: str) -> bool:
        """Mark a request as complete. Returns True if it was the current one."""
        async with self._lock:
            if self._current_request and self._current_request.request_id == request_id:
                self._current_request = None
                return True
            return False

    async def get_current_id(self) -> Optional[str]:
        """Get the current request ID."""
        async with self._lock:
            if self._current_request and not self._current_request.cancelled:
                return self._current_request.request_id
            return None


# Global tracker instance
_stt_tracker = STTRequestTracker()


def build_stt_chain() -> list[STTProvider]:
    settings = get_settings()
    providers: list[STTProvider] = []

    cloud_down = time.time() < _cloud_down_until

    preferred = settings.stt_provider.lower()
    if not cloud_down:
        # 1. Preferred provider
        if preferred == "sarvam":
            sarvam = SarvamSTT()
            if sarvam.available:
                providers.append(sarvam)
        elif preferred == "google_free":
            providers.append(GoogleFreeSTT(language="mr-IN"))
        elif preferred == "groq_whisper":
            groq = GroqWhisperSTT(language="auto")
            if groq.available:
                providers.append(groq)

        # 2. Fallbacks
        if preferred != "google_free":
            providers.append(GoogleFreeSTT(language="mr-IN"))

        if preferred != "groq_whisper" and (
            settings.groq_api_key
            or (settings.ai_api_key and settings.ai_provider.lower() == "groq")
        ):
            groq = GroqWhisperSTT(language="auto")
            if groq.available:
                providers.append(groq)

        providers.append(GoogleFreeSTT(language="en-IN"))

    local = LocalWhisperSTT()
    if local.available:
        providers.append(local)

    if cloud_down:
        logger.debug("Cloud STT skipped (outage window active); using local only.")

    return providers


def mark_cloud_outage() -> None:
    global _cloud_down_until
    _cloud_down_until = time.time() + _CLOUD_OUTAGE_SECONDS


async def transcribe_with_fallback(
    wav_bytes: bytes, sample_rate: int = 16000, chain: list[STTProvider] | None = None
) -> STTResult | None:
    """Returns STTResult, or None when every provider failed (caller should notify).

    Cloud providers run CONCURRENTLY — the first non-empty transcript wins — so a
    slow preferred provider (e.g. a hanging Groq call) never blocks a fast
    fallback. The local whisper model runs only after the whole cloud batch has
    failed.
    """
    global last_failure_kind

    # Start a new request, cancelling any previous one
    request_id = await _stt_tracker.start_request(wav_bytes, sample_rate)

    # Use provided chain or build default chain
    providers = chain if chain is not None else build_stt_chain()
    if not providers:
        last_failure_kind = "audio"
        await _stt_tracker.complete_request(request_id)
        return None

    errors: list[str] = []
    network_seen = False
    cloud = [p for p in providers if p.name != "local_whisper"]
    local = [p for p in providers if p.name == "local_whisper"]

    async def _attempt(provider: STTProvider) -> STTResult | None:
        nonlocal network_seen
        timeout_s = 8.0 if provider.name == "local_whisper" else 3.0
        try:
            async def _transcribe():
                return await provider.transcribe(wav_bytes, sample_rate)

            task = asyncio.create_task(_transcribe())
            try:
                result = await asyncio.wait_for(task, timeout=timeout_s)
            except asyncio.TimeoutError:
                errors.append(f"{provider.name}: Timeout")
                if provider.name in ("sarvam", "google_free", "groq_whisper"):
                    network_seen = True
                return None
            if not await _stt_tracker.is_current(request_id):
                return None
            return result
        except asyncio.CancelledError:
            return None
        except Exception as exc:
            errors.append(f"{provider.name}: {exc}")
            if provider.name in ("sarvam", "google_free", "groq_whisper") and _is_network_error(exc):
                network_seen = True
            return None

    async def _run_cloud() -> STTResult | None:
        pending = [asyncio.create_task(_attempt(p)) for p in cloud]
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    try:
                        result = task.result()
                    except Exception:
                        continue
                    if result is not None and result.text:
                        for other in pending:
                            other.cancel()
                        return result
        finally:
            for task in pending:
                if not task.done():
                    task.cancel()
        return None

    cloud_runner = asyncio.create_task(_run_cloud())
    await _stt_tracker.set_task(request_id, cloud_runner)

    try:
        if not await _stt_tracker.is_current(request_id):
            logger.debug("STT request %s superseded, aborting", request_id)
            cloud_runner.cancel()
            return None
        result = await cloud_runner
    except asyncio.CancelledError:
        raise

    if result is None and local:
        for provider in local:
            attempt = await _attempt(provider)
            if attempt is not None and attempt.text:
                result = attempt
                break

    if result is not None and result.text:
        logger.info(
            "STT via %s (%s): %s",
            result.provider,
            result.language,
            result.text[:80],
        )
        last_failure_kind = "ok"
        await _stt_tracker.complete_request(request_id)
        return result

    if any("Timeout" in e for e in errors) or network_seen:
        mark_cloud_outage()
    last_failure_kind = "network" if network_seen else "audio"
    if errors:
        logger.error("All STT providers failed: %s", "; ".join(errors[:4]))
    await _stt_tracker.complete_request(request_id)
    return None


__all__ = ["STTResult", "build_stt_chain", "transcribe_with_fallback"]