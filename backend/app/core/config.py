from functools import lru_cache
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _clean_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    return cleaned or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator(
        "ai_api_key", "groq_api_key", "sarvam_api_key", "email_app_password", mode="after"
    )
    @classmethod
    def _strip_secrets(cls, v):
        return _clean_secret(v)

    app_name: str = "JARVIS"
    environment: str = "dev"
    log_level: str = "INFO"
    log_dir: str = "logs"

    server_host: str = "127.0.0.1"
    server_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    user_name: str = ""
    user_address_form: str = "Sir"

    ai_provider: str = "groq"
    ai_model: str = "openai/gpt-oss-120b"
    ai_fast_model: str = "openai/gpt-oss-20b"
    ai_api_key: str = ""
    ai_base_url: str = ""

    groq_api_key: str = ""

    database_url: str = "postgresql+asyncpg://jarvis:jarvis@127.0.0.1:5433/jarvis"

    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "jarvis_memory"
    embedding_model: str = "all-MiniLM-L6-v2"

    stt_provider: str = "sarvam"
    local_stt_model: str = "base"
    tts_provider: str = "sarvam"
    tts_voice: str = ""
    tts_sample_rate: int = 22050
    sarvam_api_key: str = ""
    sarvam_stt_model: str = "saaras:v3"
    sarvam_tts_model: str = "bulbul:v3"
    sarvam_tts_speaker: str = "aditya"

    wake_word_models: str = "hey_jarvis"
    wake_word_threshold: float = 0.35
    # Voice barge-in requires headphones or AEC; on speaker+mic rigs the TTS
    # bleed falsely triggers it and cuts replies mid-sentence.
    barge_in_enabled: bool = False
    vad_enabled: bool = True
    sample_rate: int = 16000
    stt_language_hint: str = "unknown"

    voice_enabled: bool = True
    wake_greeting: str = ""
    max_followup_turns: int = 8
    phrase_silence_ms: int = 800
    phrase_max_seconds: int = 15
    phrase_preroll_ms: int = 300
    empty_listen_retries: int = 2

    agent_max_steps: int = 8
    agent_step_timeout_seconds: int = 60
    llm_request_timeout_seconds: int = 30
    voice_command_timeout_seconds: int = 10

    proactive_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"

    file_sandbox_roots: str = "Desktop,Documents,Downloads"
    email_address: str = ""
    email_app_password: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def wake_word_model_list(self) -> list[str]:
        return [m.strip() for m in self.wake_word_models.split(",") if m.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
