"""Explainable lead scoring: rules first, free LLM only as a grounded assist.

Score components match config/brand.yaml and the workflow:
contactability (20), intent (30), budget (20), timeline (20), source (10).
Every point carries a human-readable reason for the PDF and Sheet.
"""

from __future__ import annotations

import re
from typing import Any

from .config import Config
from .util import format_budget

HIGH_INTENT = (
    "site visit",
    "visit",
    "call me",
    "call back",
    "schedule",
    "appointment",
    "book a",
    "booking",
    "buy",
    "purchase",
    "ready to",
    "token amount",
    "loan approved",
    "urgent",
    "asap",
    "immediately",
    "today",
    "this week",
)
MEDIUM_INTENT = (
    "price",
    "cost",
    "rate",
    "availability",
    "available",
    "details",
    "brochure",
    "floor plan",
    "more info",
    "information",
    "quotation",
    "quote",
    "budget",
    "possession",
    "emi",
)
SPAM_TERMS = (
    "guest post",
    "seo services",
    "crypto",
    "bitcoin",
    "loan offer",
    "work from home",
    "digital marketing services",
)
SOURCE_POINTS = {
    "whatsapp": 8,
    "instagram": 8,
    "form": 7,
    "google_form": 7,
    "email": 5,
}


def _intent_keywords(message: str) -> str:
    text = (message or "").lower()
    if any(term in text for term in HIGH_INTENT):
        return "high"
    if any(term in text for term in MEDIUM_INTENT):
        return "medium"
    return "low" if text.strip() else "none"


def _intent_points(level: str) -> tuple[int, str]:
    return {
        "high": (30, "High intent: asked to buy, visit, call or schedule"),
        "medium": (18, "Medium intent: asked for price or property details"),
        "low": (6, "Low intent: general enquiry"),
        "none": (0, "No intent signal found"),
    }.get(level, (0, "No intent signal found"))


def _timeline_points(days: int | None) -> tuple[int, str]:
    if days is None:
        return 0, "Timeline not provided"
    if days <= 30:
        return 20, f"Timeline: within {max(days, 1)} days"
    if days <= 90:
        return 12, "Timeline: 1–3 months"
    if days <= 180:
        return 5, "Timeline: 3–6 months"
    return 0, "Timeline: more than 6 months"


def _location_penalty(location: str | None, config: Config) -> tuple[int, str | None]:
    areas = (config.brand.get("scoring") or {}).get("service_areas") or []
    if not location or not areas:
        return 0, None
    if any(area.lower() in location.lower() for area in areas):
        return 0, None
    return -5, f"Location outside configured service areas: {location}"


def score_lead(lead: dict[str, Any], config: Config, llm: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mutate and return a copy of the lead with score/tier/reasons."""
    lead = dict(lead)
    llm = llm or {}

    # Merge grounded LLM extractions only where the source was silent.
    if not lead.get("budget_min") and not lead.get("budget_max"):
        if llm.get("budget_min") or llm.get("budget_max"):
            lead["budget_min"] = llm.get("budget_min")
            lead["budget_max"] = llm.get("budget_max")
            lead["budget_currency"] = config.currency
    if lead.get("timeline_days") is None and llm.get("timeline_days"):
        lead["timeline_days"] = llm["timeline_days"]
        from .util import parse_timeline

        lead["timeline"] = parse_timeline(llm["timeline_days"])[0]
    for field in ("property_type", "location", "preferred_language"):
        if not lead.get(field) and llm.get(field):
            lead[field] = llm[field]

    message = lead.get("message") or ""
    keyword_intent = _intent_keywords(message)
    llm_intent = llm.get("intent")
    intent_level = keyword_intent
    intent_adjustment = 0
    if llm_intent in {"high", "medium", "low", "none"}:
        if llm_intent == "high" and keyword_intent != "high":
            intent_adjustment = 10
        elif llm_intent in {"low", "none"} and keyword_intent == "high":
            intent_adjustment = -10
        elif llm_intent == "medium" and keyword_intent == "low":
            intent_adjustment = 5

    reasons: list[str] = []
    breakdown: list[dict[str, Any]] = []

    contact_points = 0
    if lead.get("phone_e164"):
        contact_points += 10
        reasons.append("Valid phone number (+10)")
    if lead.get("email"):
        contact_points += 10
        reasons.append("Valid email address (+10)")
    if not lead.get("phone_e164") and not lead.get("email"):
        contact_points = 0
        reasons.append("No direct contact details")
    breakdown.append(
        {
            "factor": "Contactability",
            "points": contact_points,
            "max": 20,
            "evidence": ", ".join(
                item
                for item in (
                    "Phone" if lead.get("phone_e164") else None,
                    "Email" if lead.get("email") else None,
                )
                if item
            )
            or "None",
        }
    )

    intent_base, intent_reason = _intent_points(intent_level)
    intent_points = max(0, min(30, intent_base + intent_adjustment))
    reasons.append(f"{intent_reason} (+{intent_points})")
    breakdown.append(
        {
            "factor": "Intent",
            "points": intent_points,
            "max": 30,
            "evidence": intent_level.title() + (" (AI-assisted)" if intent_adjustment else ""),
        }
    )

    if lead.get("budget_min") or lead.get("budget_max"):
        budget_points = 20
        reasons.append(
            f"Budget stated: {format_budget(lead.get('budget_min'), lead.get('budget_max'), lead.get('budget_currency', 'INR'))} (+20)"
        )
        budget_evidence = format_budget(
            lead.get("budget_min"), lead.get("budget_max"), lead.get("budget_currency", "INR")
        )
    else:
        budget_points = 5
        reasons.append("Budget not stated (+5)")
        budget_evidence = "Not provided"
    breakdown.append(
        {"factor": "Budget", "points": budget_points, "max": 20, "evidence": budget_evidence}
    )

    timeline_points, timeline_reason = _timeline_points(lead.get("timeline_days"))
    reasons.append(f"{timeline_reason} (+{timeline_points})")
    breakdown.append(
        {
            "factor": "Timeline",
            "points": timeline_points,
            "max": 20,
            "evidence": lead.get("timeline") or "Not provided",
        }
    )

    source_points = SOURCE_POINTS.get(lead.get("source", ""), 3)
    if int(lead.get("touch_count") or 1) > 1:
        source_points += 2
        reasons.append("Repeat enquiry (+2)")
    source_points = min(10, source_points)
    reasons.append(f"Source: {lead.get('source_label') or lead.get('source')} (+{source_points})")
    breakdown.append(
        {
            "factor": "Source & engagement",
            "points": source_points,
            "max": 10,
            "evidence": lead.get("source_label") or lead.get("source") or "Unknown",
        }
    )

    penalty = 0
    location_penalty, location_reason = _location_penalty(lead.get("location"), config)
    if location_penalty:
        penalty += location_penalty
        reasons.append(f"{location_reason} ({location_penalty})")
    if not lead.get("phone_e164") and not lead.get("email"):
        penalty -= 20
        reasons.append("No reachable contact detail (-20)")

    is_spam = False
    text = message.lower()
    if any(term in text for term in SPAM_TERMS):
        if not lead.get("phone_e164") and not lead.get("property_type"):
            is_spam = True
            penalty -= 20
            reasons.append("Spam pattern detected (-20)")
    if text.strip() in {"test", "testing", "hello", "hi"} and not lead.get("phone_e164"):
        is_spam = True
        penalty -= 10
        reasons.append("Test/empty enquiry (-10)")

    score = max(0, min(100, contact_points + intent_points + budget_points + timeline_points + source_points + penalty))

    tier = "COLD"
    if score >= 70:
        tier = "HOT"
    elif score >= 60 and (lead.get("timeline_days") or 999) <= 30 and lead.get("phone_e164"):
        tier = "HOT"
        reasons.append("HOT override: immediate timeline + phone")
    elif score >= 40:
        tier = "WARM"
    if is_spam:
        tier = "COLD"

    lead.update(
        {
            "score": score,
            "tier": tier,
            "score_reasons": reasons,
            "score_breakdown": breakdown,
            "is_spam": is_spam,
            "llm": llm,
        }
    )
    return lead
