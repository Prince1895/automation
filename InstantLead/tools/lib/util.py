"""Small deterministic helpers shared by the pipeline.

Includes date/time handling, phone/email normalisation, currency-aware budget
parsing, timeline parsing, text cleanup and hashing. No I/O and no secrets.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AED": "AED ",
    "SGD": "S$",
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
_UNIT_MULTIPLIERS = {
    "cr": 10_000_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "l": 100_000,
    "k": 1_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
    "mm": 1_000_000,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    return (value or now_utc()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def to_tz(value: datetime | str | None, tz_name: str = "Asia/Kolkata") -> datetime | None:
    parsed = parse_datetime(value) if isinstance(value, str) else value
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo(tz_name))


def fmt_local(
    value: datetime | str | None,
    tz_name: str = "Asia/Kolkata",
    pattern: str = "%d %b %Y, %I:%M %p",
    *,
    label: str = "",
) -> str:
    parsed = to_tz(value, tz_name)
    if not parsed:
        return "Not provided"
    suffix = f" {label}" if label else ""
    return parsed.strftime(pattern) + suffix


def to_ist(value: datetime | str | None) -> datetime | None:
    return to_tz(value, "Asia/Kolkata")


def fmt_ist(value: datetime | str | None, pattern: str = "%d %b %Y, %I:%M %p IST") -> str:
    parsed = to_ist(value)
    return parsed.strftime(pattern) if parsed else "Not provided"


def clean_text(value: Any, *, max_length: int = 8000) -> str | None:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_length] if text else None


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    no_tags = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.I | re.S)
    no_tags = re.sub(r"<br\s*/?>|</p>", "\n", no_tags, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", no_tags)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_phone(raw: Any) -> tuple[str | None, str | None]:
    """Return (display, e164). Defaults to +91 for 10-digit Indian numbers."""
    if not raw:
        return None, None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None, None

    e164: str | None = None
    if len(digits) == 10 and digits[0] in "6789":
        e164 = "+91" + digits
    elif len(digits) == 11 and digits.startswith("0") and digits[1] in "6789":
        e164 = "+91" + digits[1:]
    elif len(digits) == 12 and digits.startswith("91"):
        e164 = "+" + digits
    elif len(digits) == 13 and digits.startswith("091"):
        e164 = "+91" + digits[3:]
    elif 8 <= len(digits) <= 15:
        e164 = "+" + digits

    if not e164:
        return None, None
    if e164.startswith("+91") and len(e164) == 13:
        national = e164[3:]
        return f"+91 {national[:5]} {national[5:]}", e164
    return e164, e164


def normalize_email(raw: Any) -> str | None:
    if not raw:
        return None
    match = _EMAIL_RE.search(str(raw).strip())
    return match.group(0).lower() if match else None


def extract_email(text: str | None) -> str | None:
    return normalize_email((_EMAIL_RE.search(text or "") or [None])[0])


def extract_phone(text: str | None) -> str | None:
    if not text:
        return None
    for match in _PHONE_RE.finditer(text):
        _, e164 = normalize_phone(match.group(0))
        if e164:
            return e164
    return None


def _trim_amount(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def format_inr(amount: int | float | None) -> str:
    if not amount:
        return "Not provided"
    value = float(amount)
    if value >= 10_000_000:
        return f"₹{_trim_amount(value / 10_000_000)} Cr"
    if value >= 100_000:
        return f"₹{_trim_amount(value / 100_000)} L"
    return f"₹{int(value):,}"


def format_money(amount: int | float | None, currency: str = "INR") -> str:
    """Format an amount using the configured currency.

    INR keeps the familiar Cr/L shorthand. Other currencies use K/M/B
    abbreviations so figures stay compact in emails and PDFs.
    """
    if not amount:
        return "Not provided"
    currency = (currency or "INR").upper()
    symbol = CURRENCY_SYMBOLS.get(currency, f"{currency} ")
    value = float(amount)
    if currency == "INR":
        return format_inr(value)
    if value >= 1_000_000_000:
        return f"{symbol}{_trim_amount(value / 1_000_000_000)}B"
    if value >= 1_000_000:
        return f"{symbol}{_trim_amount(value / 1_000_000)}M"
    if value >= 1_000:
        return f"{symbol}{_trim_amount(value / 1_000)}K"
    return f"{symbol}{int(value):,}"


def format_budget(
    budget_min: int | None,
    budget_max: int | None,
    currency: str = "INR",
) -> str:
    if not budget_min and not budget_max:
        return "Not provided"
    low, high = budget_min or budget_max, budget_max or budget_min
    if low == high:
        return format_money(low, currency)
    return f"{format_money(low, currency)}–{format_money(high, currency)}"


def parse_budget(raw: Any, currency: str = "INR") -> tuple[int | None, int | None, str]:
    """Parse ranges like '1.2-1.5 Cr', '50L-75L', '1200000' into INR bounds."""
    if raw is None or raw == "":
        return None, None, currency.upper()
    if isinstance(raw, (int, float)):
        value = int(raw)
        return (value, value, currency.upper()) if value > 0 else (None, None, currency.upper())

    text = str(raw).lower().replace("₹", " inr ").replace("rs.", " inr ")
    if "$" in text or "usd" in text:
        currency = "USD"
    elif "inr" in text:
        currency = "INR"

    matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|lac|l(?!\w)|k|million|mn|m(?!\w)|mm)?",
        text,
    )
    if not matches:
        return None, None, currency.upper()

    units = {unit for _, unit in matches if unit}
    single_unit = units.pop() if len(units) == 1 else None
    numbers: list[tuple[float, int | None]] = []
    for number, unit in matches:
        if not unit and single_unit:
            unit = single_unit
        multiplier = _UNIT_MULTIPLIERS.get(unit) if unit else None
        value = float(number) * (multiplier or 1)
        numbers.append((value, multiplier))

    if any(multiplier for _, multiplier in numbers):
        values = [value for value, _ in numbers]
    else:
        values = [value for value, _ in numbers if value >= 100_000]
    values = [int(value) for value in values if 10_000 <= value <= 100_000_000_000]
    if not values:
        return None, None, currency.upper()

    low, high = min(values), max(values)
    return low, high, currency.upper()


def parse_budget_from_text(text: str | None) -> tuple[int | None, int | None, str]:
    """Parse a budget only when the message contains budget context.

    Phone numbers and email addresses are removed first so a contact number can
    never be mistaken for a price. Messages without budget wording return
    ``(None, None, "INR")``.
    """
    if not text:
        return None, None, "INR"
    cleaned = _EMAIL_RE.sub(" ", text)
    cleaned = _PHONE_RE.sub(" ", cleaned)
    # "3BHK" is a configuration, not a budget number.
    cleaned = re.sub(r"\b[1-9](?:\s*\.\s*5)?\s*bhk\b", " ", cleaned, flags=re.I)
    if not re.search(
        r"(budget|price|₹|\$|usd|eur|gbp|aed|sgd|rs\.?|inr|crores?|\bcr\b|lakhs?|\blacs?\b|million|\bmn\b|\bm\b)",
        cleaned,
        re.I,
    ):
        return None, None, "INR"
    return parse_budget(cleaned)


_PROPERTY_RE = re.compile(
    r"\b([1-9](?:\s*\.\s*5)?\s*bhk|villa|plot|apartment|flat|office|shop|warehouse|penthouse|studio)\b",
    re.I,
)
_LOCATION_RE = re.compile(r"\b(?:in|at|near)\s+([A-Za-z][A-Za-z.-]{2,30})\b", re.I)
_LOCATION_STOPWORDS = {
    "the",
    "this",
    "that",
    "these",
    "those",
    "my",
    "our",
    "your",
    "buying",
    "purchasing",
    "investing",
    "looking",
    "finding",
    "selling",
    "renting",
    "rent",
    "sale",
    "touch",
    "contact",
    "case",
    "fact",
    "learning",
    "more",
    "info",
    "information",
}


def extract_property_type(text: str | None) -> str | None:
    """Return a grounded property type such as ``3BHK`` or ``Villa``."""
    if not text:
        return None
    match = _PROPERTY_RE.search(text)
    if not match:
        return None
    value = re.sub(r"\s+", "", match.group(1)).upper()
    if "BHK" in value:
        return value
    return match.group(1).title()


def extract_location(text: str | None) -> str | None:
    """Return a grounded place name mentioned after in/at/near."""
    if not text:
        return None
    for match in _LOCATION_RE.finditer(text):
        candidate = match.group(1).strip(".-")
        if candidate.lower() in _LOCATION_STOPWORDS:
            continue
        return candidate.title()
    return None


def parse_timeline(raw: Any) -> tuple[str, int | None]:
    """Return (human label, approximate days). Unknown -> ('Not provided', None)."""
    if raw is None or raw == "":
        return "Not provided", None
    if isinstance(raw, (int, float)):
        days = int(raw)
        return _timeline_label(days), days

    text = str(raw).strip().lower()
    if any(word in text for word in ("immediate", "asap", "urgent", "this week", "right away", "now")):
        return "Immediate (≤7 days)", 7
    if "next week" in text:
        return "Within 30 days", 7
    if "this month" in text or "next month" in text:
        return "Within 30 days", 30
    if any(word in text for word in ("next year", "next 1 year", "1 year", "12 months")):
        return "6–12 months", 365
    if any(word in text for word in ("not sure", "exploring", "just looking", "no timeline")):
        return "Not provided", None

    range_match = re.search(r"(\d+)\s*(?:-|to|–)\s*(\d+)\s*(day|days|week|weeks|month|months)", text)
    if range_match:
        low, high, unit = int(range_match.group(1)), int(range_match.group(2)), range_match.group(3)
        if "week" in unit:
            days = high * 7
        elif "month" in unit:
            days = high * 30
        else:
            days = high
        return _timeline_label(days, low, high, unit), days

    single = re.search(r"(\d+)\s*(day|days|week|weeks|month|months)", text)
    if single:
        amount, unit = int(single.group(1)), single.group(2)
        days = amount * (7 if "week" in unit else 30 if "month" in unit else 1)
        return _timeline_label(days), days

    return clean_text(raw, max_length=80) or "Not provided", None


def _timeline_label(days: int, low: int | None = None, high: int | None = None, unit: str = "") -> str:
    if low and high:
        return f"{low}–{high} {unit.rstrip('s')}s"
    if days <= 7:
        return "Immediate (≤7 days)"
    if days <= 30:
        return "Within 30 days"
    if days <= 90:
        return "1–3 months"
    if days <= 180:
        return "3–6 months"
    return "6–12 months"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def dedupe_hash(phone_e164: str | None, email: str | None, source: str, external_id: str) -> str:
    if phone_e164:
        return sha256_text(f"phone:{phone_e164}")
    if email:
        return sha256_text(f"email:{email}")
    return sha256_text(f"src:{source}:{external_id}")


def slugify(value: str, fallback: str = "lead") -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return text[:48] or fallback


def first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "agreed", "consent"}


def _normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_")


def flatten_mapping(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten one level of nested form payloads and normalise keys.

    Keys become snake_case so question titles such as "Full name" and
    "Contact number" match the canonical aliases.
    """
    flat: dict[str, Any] = {}
    for key, value in (data or {}).items():
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                flat[_normalize_key(child_key)] = child_value
        else:
            flat[_normalize_key(key)] = value
    return flat


def pick(data: dict[str, Any], *aliases: str) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in data.items()}
    for alias in aliases:
        if alias.lower() in lowered and lowered[alias.lower()] not in (None, ""):
            return lowered[alias.lower()]
    return None


def humanize_source(source: str) -> str:
    return {
        "form": "Website Form",
        "google_form": "Google Forms",
        "whatsapp": "WhatsApp",
        "instagram": "Instagram",
        "email": "Email",
    }.get(source, source.replace("_", " ").title())


def days_between(start: datetime | str | None, end: datetime | None = None) -> int | None:
    parsed = parse_datetime(start) if isinstance(start, str) else start
    if not parsed:
        return None
    return int(((end or now_utc()) - parsed).total_seconds() // 86400)


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
