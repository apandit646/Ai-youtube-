"""Structured JSON logging with secret redaction."""

import json
import logging
import re
import sys
from datetime import UTC, datetime

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|access_token|refresh_token|client_secret|password|authorization|secret)"
               r"([\"']?\s*[:=]\s*[\"']?)([^\s\"',&]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]+)"),
    re.compile(r"(xai-[A-Za-z0-9]{8,}|sk-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}|ya29\.[0-9A-Za-z_\-]+)"),
]


def redact(text: str) -> str:
    text = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    text = _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}***", text)
    return _SECRET_PATTERNS[2].sub("***", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key in ("job_id", "project_id", "step", "provider"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # httpx logs full URLs (which may contain API keys as query params for Gemini); keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
