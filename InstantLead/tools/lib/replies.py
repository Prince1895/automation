"""Approval-mode first replies and measurable response times.

Every eligible lead gets a deterministic, brand-consistent first reply drafted
the moment it is scored. In ``approval`` mode the draft waits for a human; in
``auto`` mode a pre-approved template is sent immediately. The time from lead
creation to send (or manual approval) is stored so the "instant response"
promise can be measured rather than assumed.
"""

from __future__ import annotations

import sqlite3
import statistics
from typing import Any

from .config import Config
from .email_render import render_first_reply
from .facts import build_lead_facts, with_valid_logo
from .leads import get_lead, update_lead
from .logging import log_info
from .util import iso_utc, parse_datetime


def _seconds_between(start: str | None, end: str | None) -> int | None:
    start_dt = parse_datetime(start)
    end_dt = parse_datetime(end)
    if not start_dt or not end_dt:
        return None
    return max(0, int((end_dt - start_dt).total_seconds()))


def get_reply(conn: sqlite3.Connection, lead_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM first_replies WHERE lead_id = ?", (lead_id,)
    ).fetchone()
    return dict(row) if row else None


def list_pending(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT r.*, l.tier, l.score, l.name, l.created_at AS lead_created_at
        FROM first_replies r
        JOIN leads l ON l.lead_id = r.lead_id
        WHERE r.status = 'draft'
        ORDER BY r.reply_id ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return "[manual]"
    local, domain = value.split("@", 1)
    return f"{local[:1]}***@{domain}"


def draft_first_reply(
    conn: sqlite3.Connection,
    lead: dict[str, Any],
    config: Config,
    *,
    actor: str = "pipeline",
) -> dict[str, Any] | None:
    """Create (or return) the first-reply draft for a lead.

    Drafting is idempotent. Spam and opted-out leads are skipped. In auto mode
    the draft is sent immediately through the same approval path.
    """
    mode = (config.first_reply_mode or "off").lower()
    if mode == "off" or lead.get("is_spam"):
        return None
    lead_id = str(lead.get("lead_id") or "")
    if not lead_id:
        return None
    if not lead.get("email") and not lead.get("phone_e164"):
        return None

    existing = get_reply(conn, lead_id)
    if existing:
        return existing

    facts = with_valid_logo(build_lead_facts(lead, config), config)
    subject, html, text = render_first_reply(facts)
    email = (lead.get("email") or "").strip()
    channel = "email" if email else "manual"
    now = iso_utc()
    draft_seconds = _seconds_between(lead.get("created_at"), now)
    conn.execute(
        """
        INSERT INTO first_replies (
            lead_id, created_at, updated_at, mode, channel, to_address, subject,
            body_text, body_html, status, drafted_at, draft_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
        """,
        (
            lead_id,
            now,
            now,
            mode,
            channel,
            email or None,
            subject,
            text,
            html,
            now,
            draft_seconds,
        ),
    )
    update_lead(conn, lead_id, first_reply_status="pending")
    conn.commit()
    reply = get_reply(conn, lead_id)
    log_info(
        "reply",
        "drafted first reply",
        lead_id=lead_id,
        channel=channel,
        mode=mode,
        draft_seconds=draft_seconds,
        actor=actor,
    )
    if mode == "auto":
        return approve_first_reply(conn, lead_id, config, actor="auto")
    return reply


def approve_first_reply(
    conn: sqlite3.Connection,
    lead_id: str,
    config: Config,
    *,
    actor: str = "human",
) -> dict[str, Any]:
    """Approve and send a pending draft. Email is sent, phone-only is marked."""
    reply = get_reply(conn, lead_id)
    if not reply:
        raise ValueError(f"No first-reply draft for lead {lead_id}")
    if reply["status"] in {"sent", "approved"}:
        return reply

    now = iso_utc()
    message_id = None
    status = "approved"
    sent_at = None
    if reply["channel"] == "email" and reply.get("to_address"):
        from .gmail import send_customer_email

        message_id = send_customer_email(
            to_address=str(reply["to_address"]),
            subject=str(reply["subject"]),
            html=str(reply["body_html"]),
            text=str(reply["body_text"]),
            lead_id=lead_id,
            config=config,
        )
        status = "sent"
        sent_at = now

    lead = get_lead(conn, lead_id) or {}
    response_seconds = _seconds_between(
        lead.get("created_at") or reply.get("created_at"), sent_at or now
    )
    conn.execute(
        """
        UPDATE first_replies
        SET status = ?, approved_at = ?, sent_at = ?, response_seconds = ?,
            gmail_message_id = ?, decided_by = ?, updated_at = ?
        WHERE lead_id = ?
        """,
        (status, now, sent_at, response_seconds, message_id, actor, now, lead_id),
    )
    update_lead(
        conn,
        lead_id,
        first_reply_at=now,
        first_reply_seconds=response_seconds,
        first_reply_status=status,
    )
    conn.commit()
    log_info(
        "reply",
        "first reply approved",
        lead_id=lead_id,
        status=status,
        response_seconds=response_seconds,
        actor=actor,
    )
    return get_reply(conn, lead_id) or reply


def reject_first_reply(
    conn: sqlite3.Connection,
    lead_id: str,
    config: Config,
    *,
    reason: str = "",
    actor: str = "human",
) -> dict[str, Any]:
    reply = get_reply(conn, lead_id)
    if not reply:
        raise ValueError(f"No first-reply draft for lead {lead_id}")
    if reply["status"] in {"sent", "approved"}:
        raise ValueError("Cannot reject a reply that is already approved or sent")
    now = iso_utc()
    conn.execute(
        """
        UPDATE first_replies
        SET status = 'rejected', decided_by = ?, updated_at = ?
        WHERE lead_id = ?
        """,
        (actor, now, lead_id),
    )
    update_lead(conn, lead_id, first_reply_status="rejected")
    conn.commit()
    log_info(
        "reply",
        "first reply rejected",
        lead_id=lead_id,
        reason=(reason or "")[:200],
        actor=actor,
    )
    return get_reply(conn, lead_id) or reply


def reply_metrics(conn: sqlite3.Connection, config: Config | None = None) -> dict[str, Any]:
    rows = conn.execute("SELECT status, response_seconds, draft_seconds FROM first_replies").fetchall()
    pending = sum(1 for row in rows if row["status"] == "draft")
    responded = [
        int(row["response_seconds"])
        for row in rows
        if row["response_seconds"] is not None and row["status"] in {"sent", "approved"}
    ]
    drafted = [int(row["draft_seconds"]) for row in rows if row["draft_seconds"] is not None]
    metrics: dict[str, Any] = {
        "total": len(rows),
        "pending": pending,
        "sent": sum(1 for row in rows if row["status"] == "sent"),
        "approved_manual": sum(1 for row in rows if row["status"] == "approved"),
        "rejected": sum(1 for row in rows if row["status"] == "rejected"),
        "median_draft_seconds": round(statistics.median(drafted), 2) if drafted else None,
        "median_response_seconds": (
            round(statistics.median(responded), 2) if responded else None
        ),
    }
    if responded:
        ordered = sorted(responded)
        index = min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))
        metrics["p90_response_seconds"] = ordered[index]
        sla_seconds = int((config.first_reply_sla_minutes if config else 5) * 60)
        metrics["within_sla"] = sum(1 for value in responded if value <= sla_seconds)
    else:
        metrics["p90_response_seconds"] = None
        metrics["within_sla"] = 0
    return metrics
