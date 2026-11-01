"""Render compact, factual lead and digest emails (HTML + plain text)."""

from __future__ import annotations

import re
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import BASE_DIR, Config


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(BASE_DIR / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _safe_subject(value: str) -> str:
    return re.sub(r"[\r\n]+", " ", value).strip()


def lead_subject(facts: dict[str, Any]) -> str:
    parts = [facts["name"]]
    requirement = " ".join(
        part
        for part in (facts["property_type"], facts["location"])
        if part and part != "Not provided"
    )
    if requirement:
        parts.append(requirement)
    if facts["budget"] != "Not provided":
        parts.append(facts["budget"])
    return _safe_subject(f"[{facts['tier']}] " + " · ".join(parts))


def render_lead_email(facts: dict[str, Any]) -> tuple[str, str, str]:
    env = _env()
    html = env.get_template("email_lead.html").render(**facts)
    text = env.get_template("email_lead.txt").render(**facts)
    return lead_subject(facts), html, text


def first_reply_subject(facts: dict[str, Any]) -> str:
    company = (facts.get("company") or {}).get("name") or "InstantLead"
    return _safe_subject(f"Re: your property enquiry · {company}")


def render_first_reply(facts: dict[str, Any]) -> tuple[str, str, str]:
    env = _env()
    html = env.get_template("lead_reply.html").render(**facts)
    text = env.get_template("lead_reply.txt").render(**facts)
    return first_reply_subject(facts), html, text


def digest_subject(facts: dict[str, Any]) -> str:
    stats = facts["stats"]
    return _safe_subject(
        f"Daily lead digest {facts['digest_date']} · {stats['total']} leads · {stats['hot']} hot"
    )


def render_digest_email(facts: dict[str, Any]) -> tuple[str, str, str]:
    env = _env()
    html = env.get_template("email_digest.html").render(**facts)
    text = env.get_template("email_digest.txt").render(**facts)
    return digest_subject(facts), html, text


def email_word_count(html: str) -> int:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    return len(re.findall(r"\b[\w₹]+\b", text))
