import asyncio
import io
import wave

from app.voice.stt.base import STTProvider, STTResult


class GoogleFreeSTT(STTProvider):
    """Free Google Web Speech fallback via the SpeechRecognition library."""

    name = "google_free"

    def __init__(self, language: str = "mr-IN") -> None:
        self.language = language

    async def transcribe(self, wav_bytes: bytes, sample_rate: int = 16000) -> STTResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_transcribe, wav_bytes)

    def _sync_transcribe(self, wav_bytes: bytes) -> STTResult:
        import speech_recognition as sr

        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            rate = wav.getframerate()
            width = wav.getsampwidth()
            channels = wav.getnchannels()
            raw = wav.readframes(wav.getnframes())

        if channels > 1:
            import audioop

            raw = audioop.tomono(raw, width, 0.5, 0.5)

        audio = sr.AudioData(raw, rate, width)
        recognizer = sr.Recognizer()
        try:
            text = recognizer.recognize_google(audio, language=self.language)
        except sr.UnknownValueError as exc:
            raise RuntimeError("Google free STT could not understand audio") from exc
        except sr.RequestError as exc:
            raise RuntimeError(f"Google free STT request failed: {exc}") from exc

        return STTResult(text=text.strip(), language=self.language, provider=self.name)
