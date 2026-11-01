"""Optional free-model extraction via OpenRouter.

Only the lead message is sent, with emails and phone numbers removed. Values
are accepted only when they are plausible and grounded in the message, and
every failure falls back to deterministic rules.
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from .config import Config
from .cost import check_budget, estimate_llm_cost, record_cost
from .logging import log_warning, safe_exception
from .util import normalize_phone

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
_ALLOWED_INTENT = {"high", "medium", "low", "none"}

SYSTEM_PROMPT = """You extract structured facts from a real-estate enquiry.
Return ONLY a JSON object with these keys:
{"intent":"high|medium|low|none","budget_min":number|null,"budget_max":number|null,
"timeline_days":number|null,"property_type":string|null,"location":string|null,
"preferred_language":string|null}
Rules:
- Extract only what is explicitly present. Never guess.
- Budget currency is {currency}. For INR, convert "cr" to 10000000 and "lakh"
  to 100000. For other currencies, return the amount as stated.
- timeline_days: immediate=7, this month=30, 1-3 months=90, 3-6 months=180.
- intent high = asks to buy/visit/call/schedule; medium = asks price/details;
  low = general enquiry; none = no property intent.
- property_type examples: 2BHK, 3BHK, villa, plot, office.
- Use null for anything not stated. Do not include explanations."""


def _sanitize_for_llm(message: str) -> str:
    text = _EMAIL_RE.sub("[email removed]", message)
    return _PHONE_RE.sub("[phone removed]", text)[:4000]


def _parse_json(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I | re.S)
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model response")
    data = json.loads(content[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model response is not an object")
    return data


def _grounded_text(value: Any, message: str) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) < 2 or len(value) > 80:
        return None
    if value.lower() in message.lower():
        return value
    tokens = [token for token in re.split(r"\W+", value.lower()) if len(token) >= 4]
    if tokens and all(token in message.lower() for token in tokens):
        return value
    return None


def validate_extraction(data: dict[str, Any], original_message: str) -> dict[str, Any]:
    message = original_message or ""
    result: dict[str, Any] = {}
    intent = str(data.get("intent", "none")).lower()
    result["intent"] = intent if intent in _ALLOWED_INTENT else "none"

    budget_values: list[int] = []
    for key in ("budget_min", "budget_max"):
        value = data.get(key)
        if value in (None, ""):
            continue
        try:
            number = int(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            continue
        if 10_000 <= number <= 100_000_000_000 and re.search(r"\d", message):
            budget_values.append(number)
    if budget_values:
        result["budget_min"] = min(budget_values)
        result["budget_max"] = max(budget_values)

    try:
        days = int(float(data.get("timeline_days"))) if data.get("timeline_days") not in (None, "") else None
    except (TypeError, ValueError):
        days = None
    if days is not None and 0 < days <= 3650:
        # Must have a timing keyword to accept LLM's day count.
        # A digit alone (like a phone number) is not enough.
        if re.search(
            r"immediate|asap|urgent|this week|next week|next month|days|weeks|months|timeline|when", message, re.I
        ):
            result["timeline_days"] = days

    for key in ("property_type", "location", "preferred_language"):
        grounded = _grounded_text(data.get(key), message)
        if grounded:
            result[key] = grounded

    return result


def extract(message: str | None, config: Config) -> dict[str, Any]:
    if not message or not config.llm_enabled or not config.openrouter_api_key:
        return {}
    prompt = _sanitize_for_llm(message)
    if not prompt.strip():
        return {}

    payload = {
        "model": config.openrouter_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT.replace("{currency}", config.currency)},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": config.llm_max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {config.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": config.public_base_url,
        "X-Title": "InstantLead",
    }

    try:
        estimate = estimate_llm_cost(config.openrouter_model, len(prompt) // 4, config.llm_max_tokens)
        check_budget(config, estimate, tool="llm")
        response = requests.post(
            f"{config.openrouter_base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.llm_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", len(prompt) // 4))
        completion_tokens = int(usage.get("completion_tokens", 0))
        cost = estimate_llm_cost(config.openrouter_model, prompt_tokens, completion_tokens)
        record_cost(
            config,
            provider="openrouter",
            model=config.openrouter_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            tool="llm",
        )
        extracted = validate_extraction(_parse_json(content), message)
        extracted["_model"] = config.openrouter_model
        return extracted
    except Exception as exc:
        log_warning("llm", "extraction failed; using rules", error=safe_exception(exc))
        return {}
