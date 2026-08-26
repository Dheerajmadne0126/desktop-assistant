import json
import logging
import re
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import get_settings

_SECRET_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|token|password|secret|authorization|subscription[_-]?key)"
    r"(?:\"|\s)?(?:\s*[=:]\s*)(?:\"|\s)?)[^\s\",}]+"
)


def _force_utf8_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                if getattr(stream, "encoding", "").lower().replace("-", "") not in (
                    "utf8",
                    "utf-8",
                ):
                    stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _SECRET_PATTERN.sub(r"\1[REDACTED]", record.msg)
        if record.args:
            record.args = tuple(
                _SECRET_PATTERN.sub(r"\1[REDACTED]", a) if isinstance(a, str) else a
                for a in record.args
            )
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    settings = get_settings()
    _force_utf8_streams()
    root = logging.getLogger("jarvis")
    if root.handlers:
        return

    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    root.addFilter(SecretRedactionFilter())
    root.propagate = False

    console_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    try:
        from rich.logging import RichHandler

        console = RichHandler(show_path=False, markup=False, rich_tracebacks=True)
        console.setLevel(console_level)
        root.addHandler(console)
    except ImportError:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
        )
        stream.setLevel(console_level)
        root.addHandler(stream)

    log_path = Path(settings.log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path / "jarvis.jsonl", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.setLevel(logging.INFO)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    if not name.startswith("jarvis"):
        name = f"jarvis.{name}"
    return logging.getLogger(name)


logger = get_logger("core")
