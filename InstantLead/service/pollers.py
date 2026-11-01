"""Poll Google Forms, Gmail (or IMAP) and Google Sheet statuses."""

from __future__ import annotations

import base64
import email
import imaplib
import json
import sqlite3
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Any

from tools.lib import sheet
from tools.lib.config import Config, ConfigError
from tools.lib.db import create_event, event_exists
from tools.lib.google import get_service
from tools.lib.leads import list_stale_leads, update_lead
from tools.lib.logging import log_info, log_warning, safe_exception
from tools.lib.util import fmt_local, iso_utc, now_utc, strip_html


def _header(message, name: str) -> str:
    raw = message.get(name, "")
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _body_text(message) -> str:
    plain: list[str] = []
    html: list[str] = []
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_disposition() == "attachment":
                continue
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            try:
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="replace")
            except (LookupError, ValueError):
                continue
            (plain if content_type == "text/plain" else html).append(decoded)
    else:
        try:
            payload = message.get_payload(decode=True) or b""
            charset = message.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            (html if message.get_content_type() == "text/html" else plain).append(decoded)
        except (LookupError, ValueError):
            pass
    text = "\n".join(plain).strip()
    return text or strip_html("\n".join(html))


def _payload_from_email(message, message_id: str | None = None) -> dict[str, Any]:
    from_name, from_email = parseaddr(_header(message, "From"))
    return {
        "message_id": message_id or _header(message, "Message-ID") or iso_utc(),
        "from_name": from_name,
        "from_email": from_email,
        "subject": _header(message, "Subject"),
        "body": _body_text(message),
        "received_at": iso_utc(),
    }


def _gmail_payload(service, msg_id: str) -> dict[str, Any]:
    raw = (
        service.users()
        .messages()
        .get(userId="me", id=msg_id, format="raw")
        .execute()
    )
    data = base64.urlsafe_b64decode(raw["raw"].encode("ascii"))
    message = email.message_from_bytes(data)
    payload = _payload_from_email(message, msg_id)
    internal = raw.get("internalDate")
    if internal:
        payload["received_at"] = datetime.fromtimestamp(
            int(internal) / 1000, tz=timezone.utc
        ).isoformat(timespec="seconds")
    return payload


def poll_forms(conn: sqlite3.Connection, config: Config) -> dict[str, int]:
    if not config.google_form_id:
        return {"seen": 0, "queued": 0}
    service = get_service("forms", "v1", config)
    form = service.forms().get(formId=config.google_form_id).execute()
    # The Forms API nests questionId under questionItem.question.
    title_map: dict[str, str] = {}
    for item in form.get("items", []):
        question = (item.get("questionItem") or {}).get("question") or {}
        if question.get("questionId"):
            title_map[question["questionId"]] = item.get("title", question["questionId"])
        for grouped in (item.get("questionGroupItem") or {}).get("questions", []):
            qid = grouped.get("questionId")
            if qid:
                title_map[qid] = item.get("title", qid)

    responses = (
        service.forms()
        .responses()
        .list(formId=config.google_form_id, pageSize=100)
        .execute()
        .get("responses", [])
    )
    queued = 0
    for response in responses:
        response_id = str(response.get("responseId", ""))
        if not response_id or event_exists(conn, "google_form", response_id):
            continue
        answers: dict[str, Any] = {}
        for question_id, answer in (response.get("answers") or {}).items():
            title = title_map.get(question_id, question_id)
            values = (answer.get("textAnswers") or {}).get("answers", [])
            answers[title] = ", ".join(str(v.get("value")) for v in values if v.get("value"))
        if response.get("respondentEmail"):
            answers.setdefault("email", response["respondentEmail"])
        payload = {
            "response_id": response_id,
            "submitted_at": response.get("lastSubmittedTime") or response.get("createTime"),
            "answers": answers,
        }
        create_event(conn, source="google_form", external_id=response_id, payload=payload)
        queued += 1
    log_info("poll_forms", "polled Google Forms", responses=len(responses), queued=queued)
    return {"seen": len(responses), "queued": queued}


def poll_gmail(conn: sqlite3.Connection, config: Config) -> dict[str, int]:
    service = get_service("gmail", "v1", config)
    listed = (
        service.users()
        .messages()
        .list(userId="me", q=config.gmail_query, maxResults=25)
        .execute()
        .get("messages", [])
    )
    queued = 0
    for item in listed:
        msg_id = str(item.get("id", ""))
        if not msg_id or event_exists(conn, "email", msg_id):
            continue
        try:
            payload = _gmail_payload(service, msg_id)
        except Exception as exc:
            log_warning("poll_email", "could not read Gmail message", error=safe_exception(exc))
            continue
        create_event(conn, source="email", external_id=msg_id, payload=payload)
        queued += 1
    log_info("poll_email", "polled Gmail", messages=len(listed), queued=queued)
    return {"seen": len(listed), "queued": queued}


def poll_imap(conn: sqlite3.Connection, config: Config) -> dict[str, int]:
    if not config.imap_user or not config.imap_app_password:
        raise ConfigError("IMAP_USER and IMAP_APP_PASSWORD are required for IMAP polling")
    client = imaplib.IMAP4_SSL(config.imap_host, config.imap_port)
    try:
        client.login(config.imap_user, config.imap_app_password)
        client.select(config.imap_folder)
        status, data = client.search(None, config.imap_search)
        if status != "OK":
            return {"seen": 0, "queued": 0}
        ids = data[0].split()[-25:]
        queued = 0
        for msg_id in ids:
            status, fetched = client.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                continue
            message = email.message_from_bytes(fetched[0][1])
            external_id = _header(message, "Message-ID") or msg_id.decode()
            if event_exists(conn, "email", external_id):
                client.store(msg_id, "+FLAGS", "\\Seen")
                continue
            payload = _payload_from_email(message, external_id)
            create_event(conn, source="email", external_id=external_id, payload=payload)
            client.store(msg_id, "+FLAGS", "\\Seen")
            queued += 1
        log_info("poll_email", "polled IMAP", fetched=len(ids), queued=queued)
        return {"seen": len(ids), "queued": queued}
    finally:
        try:
            client.logout()
        except Exception:
            pass


def poll_email(conn: sqlite3.Connection, config: Config) -> dict[str, int]:
    if config.email_source == "imap":
        return poll_imap(conn, config)
    return poll_gmail(conn, config)


def sync_statuses(conn: sqlite3.Connection, config: Config) -> dict[str, int]:
    if config.dry_run:
        return {"updated": 0}
    if not config.sheet_id:
        return {"updated": 0}
    return sheet.sync_statuses(conn, config)


def _sla_html(leads: list[dict[str, Any]], config: Config) -> str:
    rows = []
    for lead in leads:
        rows.append(
            f"<tr><td style='padding:6px;border-bottom:1px solid #eee;'><strong>{lead.get('name') or 'Not provided'}</strong>"
            f"<br><span style='color:#777;font-size:11px;'>{lead.get('lead_id')} · {lead.get('property_type') or ''} {lead.get('location') or ''}</span></td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee;'>{lead.get('phone') or lead.get('email') or 'No contact'}</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee;'>{lead.get('tier')} · {lead.get('score')}/100</td>"
            f"<td style='padding:6px;border-bottom:1px solid #eee;'>{fmt_local(lead.get('created_at'), config.business_tz, '%d %b, %I:%M %p')}</td></tr>"
        )
    return (
        "<div style='font-family:Arial,sans-serif;color:#1c2833;'>"
        "<h2 style='color:#C0392B;margin:0 0 4px;'>SLA breach — hot leads waiting</h2>"
        "<p style='font-size:13px;color:#555;margin:0 0 10px;'>These leads have no first-contact timestamp yet. Call now.</p>"
        "<table style='width:100%;border-collapse:collapse;font-size:13px;'>"
        "<tr style='background:#0F3D5C;color:#fff;'><th style='padding:6px;text-align:left;'>Lead</th>"
        "<th style='padding:6px;text-align:left;'>Contact</th><th style='padding:6px;text-align:left;'>Score</th>"
        "<th style='padding:6px;text-align:left;'>Received</th></tr>"
        + "".join(rows)
        + "</table><p style='font-size:11px;color:#777;'>Update the status in the Google Sheet to stop alerts.</p></div>"
    )


def check_sla(conn: sqlite3.Connection, config: Config) -> dict[str, int]:
    from tools.lib.gmail import send_alert

    if not config.sla_enabled:
        return {"alerts": 0}
    alerts = 0
    for tier, minutes in (("HOT", config.hot_sla_minutes), ("WARM", config.warm_sla_minutes)):
        stale = list_stale_leads(conn, tier, minutes, config.business_tz)
        if not stale:
            continue
        names = ", ".join((lead.get("name") or lead.get("lead_id") or "") for lead in stale[:3])
        subject = f"[SLA] {len(stale)} {tier} lead(s) uncontacted — {names}"
        text = "\n".join(
            f"{lead.get('name') or lead.get('lead_id')} | {lead.get('phone') or lead.get('email')} | {lead.get('tier')} {lead.get('score')}"
            for lead in stale
        )
        try:
            send_alert(subject, _sla_html(stale, config), text, config)
        except Exception as exc:
            log_warning("sla", "could not send SLA alert", error=safe_exception(exc))
            continue
        for lead in stale:
            update_lead(conn, str(lead["lead_id"]), sla_flag=f"alerted:{iso_utc()}")
        alerts += len(stale)
    if alerts:
        log_info("sla", "sent SLA alerts", leads=alerts)
    return {"alerts": alerts}
