"""Convert raw source payloads into the canonical lead shape.

Adapters are pure functions: same input -> same output. They never invent
values; missing data stays None so the PDF/email can say "Not provided".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .util import (
    as_bool,
    clean_text,
    extract_email,
    extract_location,
    extract_phone,
    extract_property_type,
    flatten_mapping,
    humanize_source,
    normalize_email,
    normalize_phone,
    parse_budget,
    parse_budget_from_text,
    parse_timeline,
    pick,
    sha256_text,
)

NAME_ALIASES = ("name", "full_name", "fullname", "your_name", "contact_name")
PHONE_ALIASES = ("phone", "mobile", "phone_number", "whatsapp", "contact_number", "mobile_number", "phone_no")
EMAIL_ALIASES = ("email", "email_address", "e_mail")
PROPERTY_ALIASES = ("property_type", "property", "requirement_type", "bhk", "configuration", "looking_for")
LOCATION_ALIASES = ("location", "city", "area", "locality", "preferred_location", "project_location")
BUDGET_ALIASES = ("budget", "budget_range", "price_range", "price", "investment")
TIMELINE_ALIASES = ("timeline", "purchase_timeline", "when", "time_to_buy", "urgency")
MESSAGE_ALIASES = ("message", "requirement", "enquiry", "inquiry", "comments", "notes", "details", "tell_us")
CONSENT_ALIASES = ("consent", "agree", "opt_in", "terms", "privacy_consent")


def _base_lead(source: str, external_id: str, received_at: str | None = None) -> dict[str, Any]:
    return {
        "source": source,
        "source_label": humanize_source(source),
        "source_external_id": external_id,
        "received_at": received_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": None,
        "phone": None,
        "phone_e164": None,
        "email": None,
        "property_type": None,
        "location": None,
        "budget_min": None,
        "budget_max": None,
        "budget_currency": "INR",
        "timeline": "Not provided",
        "timeline_days": None,
        "message": None,
        "preferred_language": None,
        "consent": False,
        "raw": {},
    }


def _apply_common(lead: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    name = clean_text(pick(data, *NAME_ALIASES), max_length=120)
    phone_raw = pick(data, *PHONE_ALIASES)
    email = normalize_email(pick(data, *EMAIL_ALIASES))
    if not email:
        email = extract_email(clean_text(pick(data, *MESSAGE_ALIASES)))
    phone_display, phone_e164 = normalize_phone(phone_raw)
    if not phone_e164:
        phone_e164 = extract_phone(clean_text(pick(data, *MESSAGE_ALIASES)))
        if phone_e164:
            phone_display, phone_e164 = normalize_phone(phone_e164)

    lead.update(
        {
            "name": name,
            "phone": phone_display,
            "phone_e164": phone_e164,
            "email": email,
            "property_type": clean_text(pick(data, *PROPERTY_ALIASES), max_length=80),
            "location": clean_text(pick(data, *LOCATION_ALIASES), max_length=120),
            "message": clean_text(pick(data, *MESSAGE_ALIASES), max_length=4000),
            "preferred_language": clean_text(
                pick(data, "language", "preferred_language", "lang"), max_length=40
            ),
            "consent": as_bool(pick(data, *CONSENT_ALIASES)),
        }
    )

    explicit_min = pick(data, "budget_min", "min_budget")
    explicit_max = pick(data, "budget_max", "max_budget")
    if explicit_min or explicit_max:
        try:
            budget_min = int(float(explicit_min)) if explicit_min not in (None, "") else None
            budget_max = int(float(explicit_max)) if explicit_max not in (None, "") else None
        except (TypeError, ValueError):
            budget_min, budget_max, currency = parse_budget(pick(data, *BUDGET_ALIASES))
        else:
            currency = str(pick(data, "budget_currency", "currency") or "INR").upper()
    else:
        budget_min, budget_max, currency = parse_budget(pick(data, *BUDGET_ALIASES))
    lead["budget_min"] = budget_min
    lead["budget_max"] = budget_max
    lead["budget_currency"] = currency

    explicit_days = pick(data, "timeline_days")
    if explicit_days not in (None, ""):
        try:
            days = int(float(explicit_days))
        except (TypeError, ValueError):
            days = None
        if days is not None:
            lead["timeline_days"] = days
            lead["timeline"] = parse_timeline(days)[0]
        else:
            lead["timeline"], lead["timeline_days"] = parse_timeline(pick(data, *TIMELINE_ALIASES))
    else:
        lead["timeline"], lead["timeline_days"] = parse_timeline(pick(data, *TIMELINE_ALIASES))

    return _enrich_from_message(lead)


def _enrich_from_message(lead: dict[str, Any]) -> dict[str, Any]:
    """Fill empty fields from free text using deterministic parsing only."""
    message = lead.get("message")
    if not message:
        return lead
    if not lead.get("budget_min") and not lead.get("budget_max"):
        budget_min, budget_max, currency = parse_budget_from_text(message)
        if budget_min or budget_max:
            lead["budget_min"] = budget_min
            lead["budget_max"] = budget_max
            lead["budget_currency"] = currency
    if lead.get("timeline_days") is None:
        label, days = parse_timeline(message)
        if days is not None:
            lead["timeline"] = label
            lead["timeline_days"] = days
    if not lead.get("property_type"):
        lead["property_type"] = extract_property_type(message)
    if not lead.get("location"):
        lead["location"] = extract_location(message)
    return lead


def _form_event(payload: dict[str, Any], received_at: str | None) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if isinstance(data.get("fields"), list):
        fields = {
            str(item.get("name", "")).strip(): item.get("value")
            for item in data["fields"]
            if isinstance(item, dict)
        }
        data = {**data, **fields}
    flat = flatten_mapping(data)
    external_id = str(
        pick(flat, "id", "lead_id", "submission_id", "external_id")
        or sha256_text(f"{received_at}:{sorted(flat.items())}")
    )
    lead = _apply_common(_base_lead("form", external_id, received_at), flat)
    lead["raw"] = payload
    return [lead]


def _google_form_event(payload: dict[str, Any], received_at: str | None) -> list[dict[str, Any]]:
    answers = payload.get("answers") or {}
    if isinstance(answers, list):
        answers = {
            str(item.get("question", "")).strip(): item.get("answer")
            for item in answers
            if isinstance(item, dict)
        }
    flat = flatten_mapping(answers)
    if not pick(flat, *EMAIL_ALIASES) and payload.get("respondentEmail"):
        flat["email"] = payload["respondentEmail"]
    # Form builders often phrase questions; map by substring when exact aliases fail.
    if not pick(flat, *MESSAGE_ALIASES):
        for key, value in flat.items():
            if any(
                word in key
                for word in ("requirement", "message", "enquiry", "inquiry", "tell_us", "details", "comments", "notes")
            ):
                flat["message"] = value
                break
    if not pick(flat, *PROPERTY_ALIASES):
        for key, value in flat.items():
            if "bhk" in key or "property" in key or "configuration" in key:
                flat["property_type"] = value
                break
    if not pick(flat, *LOCATION_ALIASES):
        for key, value in flat.items():
            if any(word in key for word in ("location", "city", "area", "locality")):
                flat["location"] = value
                break
    if not pick(flat, *TIMELINE_ALIASES):
        for key, value in flat.items():
            if any(word in key for word in ("timeline", "when", "time_to_buy", "plan_to_buy", "buy")):
                flat["timeline"] = value
                break
    if not pick(flat, *BUDGET_ALIASES):
        for key, value in flat.items():
            if any(word in key for word in ("budget", "price", "investment")):
                flat["budget"] = value
                break

    external_id = str(payload.get("response_id") or payload.get("responseId") or sha256_text(str(flat)))
    received_at = payload.get("submitted_at") or received_at
    lead = _apply_common(_base_lead("google_form", external_id, received_at), flat)
    lead["raw"] = payload
    return [lead]


def _whatsapp_events(payload: dict[str, Any], received_at: str | None) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {str(c.get("wa_id")): c.get("profile", {}) for c in value.get("contacts", [])}
            for message in value.get("messages", []):
                sender = str(message.get("from", ""))
                external_id = str(message.get("id") or sha256_text(f"{sender}:{message.get('timestamp')}"))
                contact = contacts.get(sender, {})
                text = _whatsapp_text(message)
                stamp = message.get("timestamp")
                received = (
                    datetime.fromtimestamp(int(stamp), tz=timezone.utc).isoformat(timespec="seconds")
                    if stamp
                    else received_at
                )
                phone_display, phone_e164 = normalize_phone(sender)
                lead = _base_lead("whatsapp", external_id, received)
                lead.update(
                    {
                        "name": clean_text(contact.get("name"), max_length=120),
                        "phone": phone_display,
                        "phone_e164": phone_e164,
                        "email": extract_email(text),
                        "message": text,
                        "consent": True,
                        "raw": message,
                    }
                )
                if message.get("referral"):
                    lead["raw"] = {"message": message, "referral": message.get("referral")}
                leads.append(_enrich_from_message(lead))
    return leads


def _whatsapp_text(message: dict[str, Any]) -> str | None:
    if message.get("text"):
        return clean_text(message["text"].get("body"))
    if message.get("button"):
        return clean_text(message["button"].get("text"))
    if message.get("interactive"):
        interactive = message["interactive"]
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        return clean_text(reply.get("title"))
    if message.get("image") or message.get("document") or message.get("audio") or message.get("video"):
        caption = (message.get("image") or {}).get("caption") or (message.get("document") or {}).get("caption")
        media_type = next((key for key in ("image", "document", "audio", "video") if key in message), "media")
        return clean_text(caption) or f"[{media_type} attachment]"
    return None


def _instagram_events(payload: dict[str, Any], received_at: str | None) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            message = event.get("message") or {}
            if message.get("is_echo"):
                continue
            sender = str(event.get("sender", {}).get("id", ""))
            external_id = str(message.get("mid") or sha256_text(f"{sender}:{event.get('timestamp')}"))
            text = clean_text(message.get("text"))
            if not text and message.get("attachments"):
                types = ", ".join(str(a.get("type", "attachment")) for a in message["attachments"])
                text = f"[{types} attachment]"
            stamp = event.get("timestamp")
            received = (
                datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc).isoformat(timespec="seconds")
                if stamp
                else received_at
            )
            lead = _base_lead("instagram", external_id, received)
            lead.update(
                {
                    "message": text,
                    "email": extract_email(text),
                    "phone": None,
                    "phone_e164": extract_phone(text),
                    "consent": True,
                    "raw": {"sender_id": sender, "message": message},
                }
            )
            if lead["phone_e164"]:
                lead["phone"], _ = normalize_phone(lead["phone_e164"])
            leads.append(_enrich_from_message(lead))
    return leads


def _email_event(payload: dict[str, Any], received_at: str | None) -> list[dict[str, Any]]:
    external_id = str(payload.get("message_id") or payload.get("id") or sha256_text(str(payload)))
    body = clean_text(payload.get("body") or payload.get("text"), max_length=8000)
    subject = clean_text(payload.get("subject"), max_length=200)
    from_email = normalize_email(payload.get("from_email"))
    if not from_email:
        from_email = normalize_email(payload.get("from"))
    from_name = clean_text(payload.get("from_name"), max_length=120)
    phone = extract_phone(body) or extract_phone(subject)
    display, e164 = normalize_phone(phone) if phone else (None, None)
    message = body
    if subject and subject.lower() not in (body or "").lower():
        message = f"Subject: {subject}\n\n{body or ''}".strip()
    lead = _base_lead("email", external_id, payload.get("received_at") or received_at)
    lead.update(
        {
            "name": from_name,
            "email": from_email,
            "phone": display,
            "phone_e164": e164,
            "message": message,
            "consent": True,
            "raw": payload,
        }
    )
    return [_enrich_from_message(lead)]


_EXTRACTORS = {
    "form": _form_event,
    "google_form": _google_form_event,
    "whatsapp": _whatsapp_events,
    "instagram": _instagram_events,
    "email": _email_event,
}


def extract_leads(source: str, payload: dict[str, Any], received_at: str | None = None) -> list[dict[str, Any]]:
    source = source.strip().lower()
    if source not in _EXTRACTORS:
        raise ValueError(f"Unsupported source: {source}")
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")
    return [lead for lead in _EXTRACTORS[source](payload, received_at) if lead.get("source_external_id")]


def meta_event_slices(payload: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Split a Meta webhook into one event per message.

    Returns (source, external_id, payload_for_adapter). Status-only webhooks
    produce an empty list and are ignored.
    """
    events: list[tuple[str, str, dict[str, Any]]] = []
    obj = payload.get("object")
    if obj == "whatsapp_business_account":
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    sender = str(message.get("from", ""))
                    contacts = [c for c in value.get("contacts", []) if str(c.get("wa_id")) == sender]
                    external_id = str(message.get("id") or sha256_text(f"{sender}:{message.get('timestamp')}"))
                    events.append(
                        (
                            "whatsapp",
                            external_id,
                            {"object": obj, "entry": [{"changes": [{"value": {
                                "messages": [message],
                                "contacts": contacts,
                            }}]}]},
                        )
                    )
    elif obj == "instagram":
        for entry in payload.get("entry", []):
            for messaging in entry.get("messaging", []):
                message = messaging.get("message") or {}
                if message.get("is_echo"):
                    continue
                external_id = str(
                    message.get("mid")
                    or sha256_text(f"{messaging.get('sender', {}).get('id')}:{messaging.get('timestamp')}")
                )
                events.append(
                    (
                        "instagram",
                        external_id,
                        {"object": obj, "entry": [{"messaging": [messaging]}]},
                    )
                )
    return events


def form_external_id(payload: dict[str, Any]) -> str:
    return str(
        payload.get("id")
        or payload.get("lead_id")
        or payload.get("submission_id")
        or sha256_text(str(payload))
    )
