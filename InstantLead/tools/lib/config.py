"""Load environment and brand configuration.

Purpose: one place for every runtime knob. Secrets are read from environment
variables (optionally hydrated from InstantLead/.env) and never printed.

Inputs: environment variables, config/brand.yaml, .env (optional).
Outputs: a Config object.
Example: from lib.config import get_config; cfg = get_config()
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc


def _csv(name: str, default: str = "") -> list[str]:
    raw = _env(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _path(name: str, default: str) -> Path:
    raw = _env(name, default) or default
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def _parse_clock(name: str, raw: str) -> tuple[int, int]:
    try:
        hour, minute = raw.split(":", 1)
        hour, minute = int(hour), int(minute)
    except (ValueError, AttributeError) as exc:
        raise ConfigError(f"{name} must be HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ConfigError(f"{name} must be a valid 24-hour time")
    return hour, minute


def _clock(name: str, default: str, fallback: str | None = None) -> tuple[int, int]:
    return _parse_clock(name, _env(name) or fallback or default)


def _locale_value(brand: dict[str, Any], key: str, default: str) -> str:
    locale = brand.get("locale")
    if isinstance(locale, dict) and locale.get(key) not in (None, ""):
        return str(locale[key])
    return default


@dataclass(frozen=True)
class Config:
    base_dir: Path
    brand: dict[str, Any] = field(default_factory=dict)

    dry_run: bool = False
    db_path: Path = BASE_DIR / ".tmp/instantlead.db"
    archive_dir: Path = BASE_DIR / ".tmp/archive"
    outbox_dir: Path = BASE_DIR / ".tmp/outbox"
    log_dir: Path = BASE_DIR / "logs"
    public_base_url: str = "http://localhost:8080"
    service_host: str = "0.0.0.0"
    service_port: int = 8080
    worker_enabled: bool = True
    scheduler_enabled: bool = True
    worker_poll_seconds: int = 3
    max_event_attempts: int = 6

    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_enabled: bool = True
    llm_max_tokens: int = 500
    llm_timeout_seconds: int = 20

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8765/oauth2callback"
    google_token_path: Path = BASE_DIR / ".tmp/google_token.json"

    sheet_id: str = ""
    sheet_tab: str = "Leads"
    quarantine_tab: str = "Quarantine"
    digest_tab: str = "Digest"
    drive_folder_id: str = ""
    calendar_id: str = "primary"
    sales_emails: list[str] = field(default_factory=list)
    sender_email: str = ""
    sender_name: str = ""

    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_verify_token: str = ""
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    instagram_account_id: str = ""
    form_webhook_secret: str = ""

    email_source: str = "gmail"
    gmail_query: str = "newer_than:2d -from:me"
    gmail_poll_enabled: bool = True
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_app_password: str = ""
    imap_folder: str = "INBOX"
    imap_search: str = "(UNSEEN)"
    google_form_id: str = ""
    forms_poll_enabled: bool = False

    business_tz: str = "Asia/Kolkata"
    currency: str = "INR"
    business_days: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
    business_start: tuple[int, int] = (10, 0)
    business_end: tuple[int, int] = (19, 0)
    meeting_minutes: int = 30
    slot_buffer_minutes: int = 15
    booking_horizon_hours: int = 48
    digest_time: tuple[int, int] = (19, 30)
    digest_enabled: bool = True
    hot_sla_minutes: int = 15
    warm_sla_minutes: int = 60
    sla_enabled: bool = True
    cold_email_enabled: bool = False
    message_excerpt_chars: int = 220
    retention_days: int = 365

    first_reply_mode: str = "approval"
    first_reply_sla_minutes: int = 5

    backup_enabled: bool = True
    backup_dir: Path = BASE_DIR / ".tmp/backups"
    backup_interval_hours: int = 24
    backup_retention: int = 14

    alert_check_enabled: bool = True
    alert_check_seconds: int = 60
    healthz_url: str = "http://localhost:8080/healthz"
    alert_webhook_url: str = ""
    alert_emails: list[str] = field(default_factory=list)
    dead_letter_alert_threshold: int = 1
    alert_cooldown_minutes: int = 60

    form_poll_seconds: int = 120
    email_poll_seconds: int = 120
    status_sync_seconds: int = 300
    sla_check_seconds: int = 300

    max_cost_per_run: float = 1.0
    max_cost_per_day: float = 10.0
    max_cost_per_month: float = 100.0

    def ensure_dirs(self) -> None:
        for path in (
            self.db_path.parent,
            self.archive_dir,
            self.outbox_dir,
            self.log_dir,
            self.backup_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.business_tz)

    @property
    def sheet_url(self) -> str:
        if not self.sheet_id:
            return ""
        return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}/edit"

    @property
    def has_google_oauth(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


def _load_brand(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Brand config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError("config/brand.yaml must contain a mapping")
    return data


def build_config() -> Config:
    load_dotenv(BASE_DIR / ".env", override=False)
    dry_run = _bool("DRY_RUN", False)
    brand = _load_brand(_path("BRAND_CONFIG", "config/brand.yaml"))
    business_start = _clock("BUSINESS_START", "10:00")
    business_end = _clock("BUSINESS_END", "19:00")
    if business_end <= business_start:
        raise ConfigError("BUSINESS_END must be after BUSINESS_START")

    days = tuple(int(day) for day in _csv("BUSINESS_DAYS", "0,1,2,3,4,5"))
    if not days or any(day < 0 or day > 6 for day in days):
        raise ConfigError("BUSINESS_DAYS must be comma-separated numbers 0-6")

    business_tz = _env("BUSINESS_TZ") or _locale_value(brand, "timezone", "Asia/Kolkata")
    try:
        ZoneInfo(business_tz)
    except Exception as exc:
        raise ConfigError(f"Unknown BUSINESS_TZ: {business_tz}") from exc
    currency = (
        _env("CURRENCY") or _locale_value(brand, "currency", "INR")
    ).upper()
    digest_time = _clock(
        "DIGEST_TIME", "19:30", fallback=_locale_value(brand, "digest_time", "19:30")
    )
    first_reply_mode = (_env("FIRST_REPLY_MODE", "approval") or "approval").lower()
    if first_reply_mode not in {"off", "approval", "auto"}:
        raise ConfigError("FIRST_REPLY_MODE must be off, approval or auto")
    public_base_url = _env("PUBLIC_BASE_URL", "http://localhost:8080")
    sales_emails = _csv("SALES_EMAILS")

    return Config(
        base_dir=BASE_DIR,
        brand=brand,
        dry_run=dry_run,
        db_path=_path("DB_PATH", ".tmp/instantlead.db"),
        archive_dir=_path("ARCHIVE_DIR", ".tmp/archive"),
        outbox_dir=_path("OUTBOX_DIR", ".tmp/outbox"),
        log_dir=_path("LOG_DIR", "logs"),
        public_base_url=public_base_url,
        service_host=_env("SERVICE_HOST", "0.0.0.0"),
        service_port=_int("SERVICE_PORT", 8080),
        worker_enabled=_bool("WORKER_ENABLED", True),
        scheduler_enabled=_bool("SCHEDULER_ENABLED", True),
        worker_poll_seconds=_int("WORKER_POLL_SECONDS", 3),
        max_event_attempts=_int("MAX_EVENT_ATTEMPTS", 6),
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        openrouter_model=_env("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
        openrouter_base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        llm_enabled=_bool("LLM_ENABLED", True),
        llm_max_tokens=_int("LLM_MAX_TOKENS", 500),
        llm_timeout_seconds=_int("LLM_TIMEOUT_SECONDS", 20),
        google_client_id=_env("GOOGLE_CLIENT_ID"),
        google_client_secret=_env("GOOGLE_CLIENT_SECRET"),
        google_redirect_uri=_env("GOOGLE_REDIRECT_URI", "http://localhost:8765/oauth2callback"),
        google_token_path=_path("GOOGLE_TOKEN_PATH", ".tmp/google_token.json"),
        sheet_id=_env("SHEET_ID"),
        sheet_tab=_env("SHEET_TAB", "Leads"),
        quarantine_tab=_env("QUARANTINE_TAB", "Quarantine"),
        digest_tab=_env("DIGEST_TAB", "Digest"),
        drive_folder_id=_env("DRIVE_FOLDER_ID"),
        calendar_id=_env("CALENDAR_ID", "primary"),
        sales_emails=sales_emails,
        sender_email=_env("SENDER_EMAIL"),
        sender_name=_env("SENDER_NAME"),
        meta_app_id=_env("META_APP_ID"),
        meta_app_secret=_env("META_APP_SECRET"),
        meta_verify_token=_env("META_VERIFY_TOKEN"),
        whatsapp_access_token=_env("WHATSAPP_ACCESS_TOKEN"),
        whatsapp_phone_number_id=_env("WHATSAPP_PHONE_NUMBER_ID"),
        instagram_account_id=_env("INSTAGRAM_ACCOUNT_ID"),
        form_webhook_secret=_env("FORM_WEBHOOK_SECRET"),
        email_source=_env("EMAIL_SOURCE", "gmail").lower(),
        gmail_query=_env("GMAIL_QUERY", "newer_than:2d -from:me"),
        gmail_poll_enabled=_bool("GMAIL_POLL_ENABLED", True),
        imap_host=_env("IMAP_HOST", "imap.gmail.com"),
        imap_port=_int("IMAP_PORT", 993),
        imap_user=_env("IMAP_USER"),
        imap_app_password=_env("IMAP_APP_PASSWORD"),
        imap_folder=_env("IMAP_FOLDER", "INBOX"),
        imap_search=_env("IMAP_SEARCH", "(UNSEEN)"),
        google_form_id=_env("GOOGLE_FORM_ID"),
        forms_poll_enabled=_bool("FORMS_POLL_ENABLED", False),
        business_tz=business_tz,
        currency=currency,
        business_days=days,
        business_start=business_start,
        business_end=business_end,
        meeting_minutes=_int("MEETING_MINUTES", 30),
        slot_buffer_minutes=_int("SLOT_BUFFER_MINUTES", 15),
        booking_horizon_hours=_int("BOOKING_HORIZON_HOURS", 48),
        digest_time=digest_time,
        digest_enabled=_bool("DIGEST_ENABLED", True),
        hot_sla_minutes=_int("HOT_SLA_MINUTES", 15),
        warm_sla_minutes=_int("WARM_SLA_MINUTES", 60),
        sla_enabled=_bool("SLA_ENABLED", True),
        cold_email_enabled=_bool("COLD_EMAIL_ENABLED", False),
        message_excerpt_chars=_int("MESSAGE_EXCERPT_CHARS", 220),
        retention_days=_int("RETENTION_DAYS", 365),
        first_reply_mode=first_reply_mode,
        first_reply_sla_minutes=_int("FIRST_REPLY_SLA_MINUTES", 5),
        backup_enabled=_bool("BACKUP_ENABLED", True),
        backup_dir=_path("BACKUP_DIR", ".tmp/backups"),
        backup_interval_hours=_int("BACKUP_INTERVAL_HOURS", 24),
        backup_retention=_int("BACKUP_RETENTION", 14),
        alert_check_enabled=_bool("ALERT_CHECK_ENABLED", True),
        alert_check_seconds=_int("ALERT_CHECK_SECONDS", 60),
        healthz_url=_env("HEALTHZ_URL", f"{public_base_url.rstrip('/')}/healthz"),
        alert_webhook_url=_env("ALERT_WEBHOOK_URL"),
        alert_emails=_csv("ALERT_EMAILS") or sales_emails,
        dead_letter_alert_threshold=_int("DEAD_LETTER_ALERT_THRESHOLD", 1),
        alert_cooldown_minutes=_int("ALERT_COOLDOWN_MINUTES", 60),
        form_poll_seconds=_int("FORM_POLL_SECONDS", 120),
        email_poll_seconds=_int("EMAIL_POLL_SECONDS", 120),
        status_sync_seconds=_int("STATUS_SYNC_SECONDS", 300),
        sla_check_seconds=_int("SLA_CHECK_SECONDS", 300),
        max_cost_per_run=_float("MAX_COST_PER_RUN", 1.0),
        max_cost_per_day=_float("MAX_COST_PER_DAY", 10.0),
        max_cost_per_month=_float("MAX_COST_PER_MONTH", 100.0),
    )


@functools.lru_cache(maxsize=1)
def get_config() -> Config:
    cfg = build_config()
    cfg.ensure_dirs()
    return cfg


def reset_config_cache() -> None:
    get_config.cache_clear()
