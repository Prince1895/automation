"""Synthetic leads for benchmarks and clean demo runs.

The generator is deterministic for a given seed. Each record carries the
source payload plus the expected tier/spam label, so benchmark accuracy is
measured against labels we control rather than against the scorer itself.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

CITIES = ["Bengaluru", "Mumbai", "Pune", "Hyderabad"]
PROPERTIES = ["2BHK", "3BHK", "villa", "plot"]
FIRST_NAMES = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Sara", "Vivaan", "Isha"]
LAST_NAMES = ["Rao", "Shah", "Nair", "Mehta", "Kapoor", "Iyer", "Bose", "Patel"]
BASE_TIME = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)


def _iso(index: int) -> str:
    return (BASE_TIME + timedelta(minutes=index)).isoformat(timespec="seconds")


def _person(index: int, rng: random.Random) -> dict[str, str]:
    first = FIRST_NAMES[index % len(FIRST_NAMES)]
    last = LAST_NAMES[(index // len(FIRST_NAMES)) % len(LAST_NAMES)]
    phone = f"9{index % 10}{(index * 7919) % 1_000_000_000:09d}"[-10:]
    email = f"lead{index:03d}@example.test"
    return {
        "name": f"{first} {last}",
        "phone": phone,
        "email": email,
        "city": CITIES[index % len(CITIES)],
        "property": PROPERTIES[index % len(PROPERTIES)],
    }


def _category(index: int) -> str:
    slot = index % 20
    if slot < 8:
        return "HOT"
    if slot < 15:
        return "WARM"
    if slot < 19:
        return "COLD"
    return "SPAM"


def _source(index: int) -> str:
    return ["form", "whatsapp", "google_form", "instagram", "email"][index % 5]


def _messages(category: str, person: dict[str, str]) -> tuple[str, dict[str, Any]]:
    city, prop = person["city"], person["property"]
    if category == "HOT":
        message = (
            f"I want to buy a {prop} in {city} and book a site visit this week. "
            "Budget 1.2-1.5 Cr. Please call me."
        )
        fields = {
            "budget": "1.2-1.5 Cr",
            "timeline": "this week",
        }
    elif category == "WARM":
        message = f"Please share the price and brochure for a {prop} in {city}."
        fields = {"budget": "1.2-1.5 Cr", "timeline": "6 months"}
    elif category == "COLD":
        message = "Just looking around at options, no rush."
        fields = {}
    else:
        message = (
            "We provide guest post and seo services for crypto and bitcoin projects. "
            "Work from home offers available."
        )
        fields = {}
    return message, fields


def _form_payload(index: int, person: dict[str, str], message: str, fields: dict, category: str) -> dict:
    data: dict[str, Any] = {
        "name": person["name"],
        "phone": person["phone"] if category != "SPAM" else "",
        "property_type": person["property"] if category != "SPAM" else "",
        "location": person["city"],
        "message": message,
        "consent": "yes",
    }
    if category in {"HOT", "COLD"}:
        data["email"] = person["email"]
    data.update(fields)
    return {"id": f"DEMO-FORM-{index:04d}", "submitted_at": _iso(index), "data": data}


def _google_form_payload(index: int, person: dict[str, str], message: str, fields: dict, category: str) -> dict:
    answers = {
        "Full name": person["name"],
        "Contact number": person["phone"],
        "Which property are you looking for?": person["property"],
        "Preferred location": person["city"],
        "Tell us about your requirement": message,
    }
    if fields.get("timeline"):
        answers["When do you plan to buy?"] = fields["timeline"]
    if fields.get("budget"):
        answers["Budget"] = fields["budget"]
    payload: dict[str, Any] = {
        "response_id": f"DEMO-GFORM-{index:04d}",
        "submitted_at": _iso(index),
        "answers": answers,
    }
    if category in {"HOT", "COLD"}:
        payload["respondentEmail"] = person["email"]
    return payload


def _whatsapp_payload(index: int, person: dict[str, str], message: str) -> dict:
    sender = f"91{person['phone']}"
    body = message
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "DEMO-WA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "contacts": [
                                {"wa_id": sender, "profile": {"name": person["name"]}}
                            ],
                            "messages": [
                                {
                                    "from": sender,
                                    "id": f"wamid.DEMO-{index:04d}",
                                    "timestamp": str(int((BASE_TIME + timedelta(minutes=index)).timestamp())),
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _instagram_payload(index: int, person: dict[str, str], message: str, category: str) -> dict:
    body = message
    if category in {"HOT", "WARM"}:
        body = f"{message} Call me on {person['phone']}."
    return {
        "object": "instagram",
        "entry": [
            {
                "id": "DEMO-IG",
                "messaging": [
                    {
                        "sender": {"id": f"IG-DEMO-{index:04d}"},
                        "recipient": {"id": "DEMO-IG"},
                        "timestamp": int((BASE_TIME + timedelta(minutes=index)).timestamp() * 1000),
                        "message": {"mid": f"mid.DEMO-{index:04d}", "text": body},
                    }
                ],
            }
        ],
    }


def _email_payload(index: int, person: dict[str, str], message: str, category: str, fields: dict) -> dict:
    body = message
    if category in {"HOT", "WARM"}:
        body = f"{message}\n\nYou can reach me on +91 {person['phone']}."
    return {
        "message_id": f"DEMO-EMAIL-{index:04d}",
        "from_name": person["name"],
        "from_email": person["email"],
        "subject": f"Enquiry: {person['property']} in {person['city']}",
        "received_at": _iso(index),
        "body": body,
    }


def generate_demo_leads(count: int = 100, seed: int = 42) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for index in range(count):
        category = _category(index)
        source = _source(index)
        person = _person(index, rng)
        message, fields = _messages(category, person)

        if category == "SPAM":
            source = "form"
        if source == "form":
            payload = _form_payload(index, person, message, fields, category)
        elif source == "google_form":
            payload = _google_form_payload(index, person, message, fields, category)
        elif source == "whatsapp":
            payload = _whatsapp_payload(index, person, message)
        elif source == "instagram":
            payload = _instagram_payload(index, person, message, category)
        else:
            payload = _email_payload(index, person, message, category, fields)

        records.append(
            {
                "source": source,
                "payload": payload,
                "expected_tier": "COLD" if category == "SPAM" else category,
                "expected_category": category,
                "expected_spam": category == "SPAM",
                "demo_index": index,
            }
        )
    return records
