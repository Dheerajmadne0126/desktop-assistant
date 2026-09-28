import asyncio
import os
import re

from app.core.config import get_settings
from app.core.logging import get_logger
from app.voice.tts.base import (
    TTSProvider,
    play_audio_file,
    play_audio_stream,
    sanitize_for_speech,
    stop_speaking,
)
from app.voice.tts.edge import EdgeTTS
from app.voice.tts.sarvam import SarvamTTS

logger = get_logger("tts")


def build_tts_chain() -> list[TTSProvider]:
    settings = get_settings()
    chain: list[TTSProvider] = []
    if settings.tts_provider == "sarvam":
        sarvam = SarvamTTS()
        if sarvam.available:
            chain.append(sarvam)
    chain.append(EdgeTTS())
    return chain


def _chunk_text(text: str) -> list[str]:
    # Split only on major sentence boundaries to avoid excessive chunking
    # Split on . ? ! । (major sentence terminators) only
    parts = re.split(r'([.?!।]+)', text)
    chunks = []
    current = ""
    for part in parts:
        current += part
        if re.search(r'[.?!।]', part):
            if len(current.strip()) > 5:
                chunks.append(current.strip())
                current = ""
    if current.strip():
        if len(current.strip()) < 10 and chunks:
            chunks[-1] += " " + current.strip()
        else:
            chunks.append(current.strip())
    if not chunks:
        chunks = [text]
    return chunks


async def speak_text(text: str, language: str = "English") -> bool:
    """Sanitizes, synthesizes and plays text. Returns False when interrupted."""
    from app.voice.tts.base import reset_stop_flag, _stop_event

    speech = sanitize_for_speech(text)
    if not speech:
        return True

    reset_stop_flag()
    chunks = _chunk_text(speech)
    last_error: Exception | None = None
    
    for provider in build_tts_chain():
        try:
            logger.info("TTS via %s (%s): %s", provider.name, language, speech[:60])
            
            import time
            t0 = time.perf_counter()
            
            # Use streaming if provider supports it and we have multiple chunks
            if len(chunks) > 1 and hasattr(provider, 'synthesize_stream'):
                logger.info("Using streaming TTS for %d chunks", len(chunks))
                
                async def chunk_generator():
                    for i, chunk in enumerate(chunks):
                        if _stop_event.is_set():
                            break
                        # For Edge TTS, use streaming synthesis
                        async for audio_chunk in provider.synthesize_stream(chunk, language):
                            yield audio_chunk
                
                completed = await play_audio_stream(chunk_generator())
                if not completed:
                    logger.info("TTS interrupted during streaming")
                return completed
            
            # Fallback: synthesize full chunks sequentially
            if len(chunks) == 1:
                audio_bytes = await provider.synthesize(chunks[0], language)
                logger.info("TTFA (Time To First Audio): %dms", int((time.perf_counter() - t0) * 1000))
                return await play_audio_file(audio_bytes)
                
            next_task = asyncio.create_task(provider.synthesize(chunks[0], language))
            completed = True
            
            for i in range(len(chunks)):
                if _stop_event.is_set():
                    completed = False
                    break
                    
                audio_bytes = await next_task
                if i == 0:
                    logger.info("TTFA (Time To First Audio) for streaming: %dms", int((time.perf_counter() - t0) * 1000))
                
                if i + 1 < len(chunks):
                    next_task = asyncio.create_task(provider.synthesize(chunks[i + 1], language))
                    
                completed = await play_audio_file(audio_bytes)
                if not completed:
                    break
                    
            return completed
            
        except Exception as exc:
            logger.warning("TTS provider %s failed: %s", provider.name, exc)
            last_error = exc

    logger.error("All TTS providers failed: %s", last_error)
    return False


async def speak_text_stream(text: str, language: str = "English") -> bool:
    """Stream version of speak_text that synthesizes and plays in one go with streaming.
    
    This is a simplified version that synthesizes the full text and streams playback.
    """
    from app.voice.tts.base import reset_stop_flag, _stop_event, play_audio_stream
    
    speech = sanitize_for_speech(text)
    if not speech:
        return True

    reset_stop_flag()
    last_error: Exception | None = None
    
    for provider in build_tts_chain():
        try:
            logger.info("TTS stream via %s (%s): %s", provider.name, language, speech[:60])
            
            import time
            t0 = time.perf_counter()
            
            # Use streaming synthesis if available
            if hasattr(provider, 'synthesize_stream'):
                logger.info("Using streaming TTS synthesis")
                
                async def chunk_generator():
                    async for audio_chunk in provider.synthesize_stream(speech, language):
                        if _stop_event.is_set():
                            break
                        yield audio_chunk
                
                completed = await play_audio_stream(chunk_generator())
                if not completed:
                    logger.info("TTS interrupted during streaming")
                return completed
            
            # Fallback: synthesize all at once, stream playback
            audio_bytes = await provider.synthesize(speech, language)
            logger.info("TTFA (Time To First Audio): %dms", int((time.perf_counter() - t0) * 1000))
            return await play_audio_stream(iter([audio_bytes]))
            
        except Exception as exc:
            logger.warning("TTS provider %s failed: %s", provider.name, exc)
            last_error = exc

    logger.error("All TTS providers failed: %s", last_error)
    return False


__all__ = ["speak_text", "speak_text_stream", "stop_speaking"]