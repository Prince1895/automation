"""Structured JSONL logging with PII and secret redaction.

Never log raw payloads, phone numbers, emails, names, message bodies, tokens,
or API keys. Errors are sanitised before they reach disk.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_config

_LOCK = threading.Lock()
_SECRET_KEY_RE = re.compile(r"(secret|token|key|password|authorization|credential)", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
_MAX_STRING = 600


def _sanitize(value: Any, key: str = "") -> Any:
    if _SECRET_KEY_RE.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {k: _sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        value = _EMAIL_RE.sub("[email]", value)
        value = _PHONE_RE.sub("[phone]", value)
        return value[:_MAX_STRING]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_STRING]


def _write(tool: str, level: str, message: str, fields: dict[str, Any]) -> None:
    cfg = get_config()
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool,
        "level": level,
        "message": _sanitize(message),
        **{k: _sanitize(v, k) for k, v in fields.items()},
    }
    line = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
    path = cfg.log_dir / f"{tool}-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
    with _LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def log_info(tool: str, message: str, **fields: Any) -> None:
    _write(tool, "info", message, fields)


def log_warning(tool: str, message: str, **fields: Any) -> None:
    _write(tool, "warning", message, fields)


def log_error(tool: str, message: str, **fields: Any) -> None:
    _write(tool, "error", message, fields)


def safe_exception(exc: BaseException) -> str:
    """Return a short, sanitised error string safe for logs and APIs."""
    text = f"{type(exc).__name__}: {exc}"
    return str(_sanitize(text))


def write_snapshot(directory: Path, name: str, payload: dict[str, Any]) -> Path:
    """Write a PII-containing intermediate with owner-only permissions."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path
