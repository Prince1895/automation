"""Build the single canonical fact set used by both PDF and email templates.

Both deliverables read from this module, so they cannot disagree. Missing
values are rendered as "Not provided" rather than guessed.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .config import Config
from .util import (
    fmt_local,
    format_budget,
    now_utc,
    slugify,
    to_tz,
)

NOT_PROVIDED = "Not provided"


def _value(value: Any) -> str:
    if value in (None, "", []):
        return NOT_PROVIDED
    return str(value)


def _excerpt(message: str | None, limit: int) -> str:
    if not message:
        return NOT_PROVIDED
    # Excerpts should be single-line for table layouts
    text = re.sub(r"\s+", " ", message).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def _wa_number(phone_e164: str | None) -> str:
    return re.sub(r"\D", "", phone_e164 or "")


def _next_action(lead: dict[str, Any], config: Config) -> str:
    tier = lead.get("tier")
    days = lead.get("timeline_days")
    phone = lead.get("phone") or lead.get("phone_e164")
    if lead.get("is_spam"):
        return "No outreach. Review and quarantine if confirmed spam."
    if tier == "HOT":
        if phone:
            return f"Call now and confirm the requested visit. Target first response: {config.hot_sla_minutes} minutes."
        return f"Email now to get a phone number and confirm the requested visit. Target first response: {config.hot_sla_minutes} minutes."
    if tier == "WARM":
        suffix = " Confirm budget and timeline." if not lead.get("budget_min") else " Confirm the preferred visit slot."
        if phone:
            return f"Call today to qualify the enquiry.{suffix} Target: {config.warm_sla_minutes} minutes."
        return f"Email today to get a phone number and qualify the enquiry.{suffix} Target: {config.warm_sla_minutes} minutes."
    if days and days <= 30:
        if phone:
            return "Nurture with a quick call; timeline is near-term."
        return "Nurture with an email; timeline is near-term."
    return "Nurture via the daily digest and follow up when capacity allows."


def build_lead_facts(lead: dict[str, Any], config: Config) -> dict[str, Any]:
    company = config.brand.get("company", {})
    colors = config.brand.get("colors", {})
    footer = config.brand.get("footer", {})
    tier = (lead.get("tier") or "COLD").upper()
    currency = lead.get("budget_currency") or config.currency
    budget = format_budget(lead.get("budget_min"), lead.get("budget_max"), currency)
    phone = lead.get("phone") or lead.get("phone_e164")
    email = lead.get("email")
    wa = _wa_number(lead.get("phone_e164"))
    sheet_url = config.sheet_url
    if sheet_url and lead.get("sheet_row"):
        sheet_url = f"{sheet_url}#gid=0&range=A{lead['sheet_row']}"

    links = {
        "call": f"tel:{lead['phone_e164']}" if lead.get("phone_e164") else "",
        "whatsapp": f"https://wa.me/{wa}" if wa else "",
        "email": f"mailto:{email}" if email else "",
        "meet": lead.get("meet_link") or "",
        "sheet": sheet_url,
        "pdf": lead.get("pdf_drive_link") or "",
        "website": company.get("website", ""),
    }

    return {
        "lead_id": lead.get("lead_id", ""),
        "tier": tier,
        "tier_class": tier.lower(),
        "score": lead.get("score") or 0,
        "name": _value(lead.get("name")),
        "phone": _value(phone),
        "phone_e164": lead.get("phone_e164") or "",
        "email": _value(email),
        "property_type": _value(lead.get("property_type")),
        "location": _value(lead.get("location")),
        "budget": budget,
        "timeline": _value(lead.get("timeline")),
        "source": lead.get("source_label") or _value(lead.get("source")),
        "status": _value(lead.get("status") or "New"),
        "message": lead.get("message") or NOT_PROVIDED,
        "message_excerpt": _excerpt(lead.get("message"), config.message_excerpt_chars),
        "message_is_truncated": bool(
            lead.get("message") and len(lead["message"]) > config.message_excerpt_chars
        ),
        "received_at": fmt_local(
            lead.get("created_at") or lead.get("received_at"), config.business_tz
        ),
        "received_day": (
            to_tz(lead.get("created_at"), config.business_tz).strftime("%d %b %Y")
            if lead.get("created_at")
            else NOT_PROVIDED
        ),
        "consent": "Yes" if lead.get("consent") else "Not recorded",
        "consent_flag": bool(lead.get("consent")),
        "reasons": lead.get("score_reasons") or [],
        "breakdown": lead.get("score_breakdown") or _fallback_breakdown(lead),
        "next_action": _next_action(lead, config),
        "reply_sla_minutes": config.first_reply_sla_minutes,
        "touch_count": int(lead.get("touch_count") or 1),
        "calendar_start": (
            fmt_local(lead.get("calendar_start"), config.business_tz)
            if lead.get("calendar_start")
            else NOT_PROVIDED
        ),
        "links": links,
        "company": {
            "name": company.get("name", "InstantLead"),
            "legal_name": company.get("legal_name", company.get("name", "InstantLead")),
            "tagline": company.get("tagline", ""),
            "website": company.get("website", ""),
            "phone": company.get("phone", ""),
            "email": company.get("email", ""),
            "address": company.get("address", ""),
            "logo": company.get("logo", ""),
        },
        "colors": colors,
        "footer": footer,
        "provenance": {
            "source": lead.get("source_label") or lead.get("source"),
            "external_id": lead.get("source_external_id") or NOT_PROVIDED,
            "received_at": fmt_local(lead.get("created_at"), config.business_tz),
            "retention": f"{config.retention_days} days",
        },
        "generated_at": fmt_local(now_utc(), config.business_tz),
        "generated_day": datetime.now(config.tz).strftime("%Y-%m-%d"),
        "path_slug": slugify(f"{lead.get('name') or lead.get('lead_id')}-{lead.get('location') or ''}"),
        "checklist": [
            "Email the lead to get a phone number and confirm requirement" if not phone else "Call the lead and confirm the requirement",
            "Qualify budget, location and timeline",
            "Book or confirm the site visit / meeting",
            "Update the status in the Google Sheet so SLA tracking stops",
        ],
    }


def _fallback_breakdown(lead: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"factor": "Total score", "points": lead.get("score") or 0, "max": 100, "evidence": "Scored"},
    ]


def build_digest_facts(
    leads: list[dict[str, Any]],
    config: Config,
    digest_date: str,
    stats: dict[str, Any],
) -> dict[str, Any]:
    company = config.brand.get("company", {})
    colors = config.brand.get("colors", {})
    footer = config.brand.get("footer", {})
    rows = []
    for lead in leads:
        facts = build_lead_facts(lead, config)
        rows.append(
            {
                "lead_id": facts["lead_id"],
                "tier": facts["tier"],
                "tier_class": facts["tier_class"],
                "score": facts["score"],
                "name": facts["name"],
                "phone": facts["phone"],
                "email": facts["email"],
                "location": facts["location"],
                "budget": facts["budget"],
                "timeline": facts["timeline"],
                "source": facts["source"],
                "status": facts["status"],
                "received_at": facts["received_at"],
                "meet_link": facts["links"]["meet"],
                "pdf_link": facts["links"]["pdf"],
                "sheet_url": facts["links"]["sheet"],
            }
        )
    return {
        "digest_date": digest_date,
        "generated_at": fmt_local(now_utc(), config.business_tz),
        "company": {
            "name": company.get("name", "InstantLead"),
            "website": company.get("website", ""),
            "phone": company.get("phone", ""),
            "email": company.get("email", ""),
            "logo": company.get("logo", ""),
        },
        "colors": colors,
        "footer": footer,
        "stats": stats,
        "hot": [row for row in rows if row["tier"] == "HOT"],
        "warm": [row for row in rows if row["tier"] == "WARM"],
        "cold": [row for row in rows if row["tier"] == "COLD"],
        "rows": rows,
        "generated_day": digest_date,
    }


def with_valid_logo(facts: dict[str, Any], config: Config) -> dict[str, Any]:
    """Return a copy with the logo cleared when the file is missing."""
    from pathlib import Path

    result = dict(facts)
    company = dict(result.get("company") or {})
    logo = company.get("logo") or ""
    if logo:
        path = Path(logo)
        if not path.is_absolute():
            path = config.base_dir / path
        company["logo"] = str(path) if path.exists() else ""
    result["company"] = company
    return result
