from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class STTResult:
    text: str
    language: str = "unknown"
    provider: str = ""
    confidence: float | None = None


class STTProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def transcribe(self, wav_bytes: bytes, sample_rate: int = 16000) -> STTResult:
        ...
