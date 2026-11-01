"""GDPR-style lead erasure.

Removes the lead row, its pipeline steps, first-reply drafts, related queue
events (including duplicate payloads that still contain the same contact
details), and local PDF/email artifacts. Remote copies (Drive, Sheet, Gmail)
must be removed with the provider's own retention tooling; callers get a clear
warning so erasure is not silently incomplete.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .leads import get_lead
from .logging import log_info


def _find_ids(
    conn: sqlite3.Connection,
    *,
    lead_ids: Iterable[str] = (),
    emails: Iterable[str] = (),
    phones: Iterable[str] = (),
) -> list[str]:
    found: set[str] = set()
    for lead_id in lead_ids:
        if lead_id and get_lead(conn, lead_id):
            found.add(lead_id)
    for email in emails:
        rows = conn.execute(
            "SELECT lead_id FROM leads WHERE lower(email) = lower(?)", (email,)
        ).fetchall()
        found.update(str(row["lead_id"]) for row in rows)
    for phone in phones:
        rows = conn.execute(
            "SELECT lead_id FROM leads WHERE phone_e164 = ?", (phone,)
        ).fetchall()
        found.update(str(row["lead_id"]) for row in rows)
    return sorted(found)


def preview_erasure(
    conn: sqlite3.Connection,
    *,
    lead_ids: Iterable[str] = (),
    emails: Iterable[str] = (),
    phones: Iterable[str] = (),
) -> dict[str, Any]:
    ids = _find_ids(conn, lead_ids=lead_ids, emails=emails, phones=phones)
    if not ids:
        return {"leads": [], "count": 0}
    placeholders = ", ".join("?" for _ in ids)
    events = conn.execute(
        f"SELECT COUNT(*) AS c FROM events WHERE lead_id IN ({placeholders})", ids
    ).fetchone()["c"]
    replies = conn.execute(
        f"SELECT COUNT(*) AS c FROM first_replies WHERE lead_id IN ({placeholders})", ids
    ).fetchone()["c"]
    return {
        "leads": ids,
        "count": len(ids),
        "events": int(events),
        "first_replies": int(replies),
    }


def _remove_files(config: Config, lead: dict[str, Any]) -> list[str]:
    removed: list[str] = []
    lead_id = str(lead.get("lead_id") or "")
    candidates: list[Path] = []
    pdf = lead.get("pdf_local_path")
    if pdf:
        candidates.append(Path(pdf))
    if lead_id:
        candidates.extend(config.archive_dir.glob(f"*{lead_id}*"))
        candidates.extend(config.outbox_dir.glob(f"*{lead_id}*.eml"))
    for path in candidates:
        try:
            resolved = path.resolve()
            if resolved.is_file() and (
                resolved.is_relative_to(config.archive_dir.resolve())
                or resolved.is_relative_to(config.outbox_dir.resolve())
            ):
                resolved.unlink()
                removed.append(str(resolved))
        except (OSError, ValueError):
            continue
    return removed


def erase_leads(
    conn: sqlite3.Connection,
    config: Config,
    *,
    lead_ids: Iterable[str] = (),
    emails: Iterable[str] = (),
    phones: Iterable[str] = (),
    delete_files: bool = True,
) -> dict[str, Any]:
    ids = _find_ids(conn, lead_ids=lead_ids, emails=emails, phones=phones)
    if not ids:
        return {"ok": True, "deleted": [], "count": 0, "files": [], "warnings": []}

    leads = [get_lead(conn, lead_id) or {"lead_id": lead_id} for lead_id in ids]
    placeholders = ", ".join("?" for _ in ids)
    email_terms: set[str] = set()
    phone_terms: set[str] = set()
    for lead in leads:
        if lead.get("email"):
            email_terms.add(str(lead["email"]).lower())
        if lead.get("phone_e164"):
            phone_terms.add(str(lead["phone_e164"]).replace("+", ""))

    try:
        conn.execute("BEGIN IMMEDIATE")
        event_count = 0
        for term in email_terms:
            cursor = conn.execute(
                "DELETE FROM events WHERE lower(payload_json) LIKE ?", (f"%{term}%",)
            )
            event_count += cursor.rowcount
        for term in phone_terms:
            digits_only = (
                "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(payload_json, ' ', ''), '-', ''),"
                " '(', ''), ')', ''), '+', '')"
            )
            cursor = conn.execute(
                f"DELETE FROM events WHERE {digits_only} LIKE ?", (f"%{term}%",)
            )
            event_count += cursor.rowcount
        cursor = conn.execute(
            f"DELETE FROM events WHERE lead_id IN ({placeholders})", ids
        )
        event_count += cursor.rowcount
        conn.execute(f"DELETE FROM first_replies WHERE lead_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM lead_steps WHERE lead_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM llm_usage WHERE lead_id IN ({placeholders})", ids)
        conn.execute(f"DELETE FROM leads WHERE lead_id IN ({placeholders})", ids)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    files: list[str] = []
    if delete_files:
        for lead in leads:
            files.extend(_remove_files(config, lead))

    warnings = [
        "Remote copies (Google Sheet, Drive PDF, sent Gmail messages) are not "
        "deleted automatically; remove them with the provider's admin tools.",
    ]
    result = {
        "ok": True,
        "deleted": ids,
        "count": len(ids),
        "events_deleted": event_count,
        "files": files,
        "warnings": warnings,
    }
    log_info(
        "delete_lead",
        "lead data erased",
        leads=ids,
        events=event_count,
        files=len(files),
    )
    return result
