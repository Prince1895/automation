"""Lead persistence, cross-source deduplication and pipeline step tracking."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from .util import dedupe_hash, humanize_source, iso_utc, now_utc, to_ist, to_tz

LEAD_COLUMNS = (
    "lead_id",
    "created_at",
    "updated_at",
    "source",
    "source_external_id",
    "name",
    "phone",
    "phone_e164",
    "email",
    "property_type",
    "location",
    "budget_min",
    "budget_max",
    "budget_currency",
    "timeline",
    "timeline_days",
    "message",
    "preferred_language",
    "consent",
    "raw_json",
    "dedupe_hash",
    "touch_count",
    "score",
    "tier",
    "is_spam",
    "score_reasons_json",
    "score_breakdown_json",
    "llm_json",
    "status",
    "owner",
    "assigned_at",
    "first_contact_at",
    "calendar_event_id",
    "calendar_start",
    "meet_link",
    "pdf_local_path",
    "pdf_drive_link",
    "sheet_row",
    "gmail_message_id",
    "digest_date",
    "sla_flag",
)

_MERGE_FIELDS = (
    "name",
    "phone",
    "phone_e164",
    "email",
    "property_type",
    "location",
    "budget_min",
    "budget_max",
    "budget_currency",
    "timeline",
    "timeline_days",
    "message",
    "preferred_language",
)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    if data.get("score_reasons_json"):
        try:
            data["score_reasons"] = json.loads(data["score_reasons_json"])
        except json.JSONDecodeError:
            data["score_reasons"] = []
    else:
        data["score_reasons"] = []
    if data.get("llm_json"):
        try:
            data["llm"] = json.loads(data["llm_json"])
        except json.JSONDecodeError:
            data["llm"] = {}
    else:
        data["llm"] = {}
    if data.get("score_breakdown_json"):
        try:
            data["score_breakdown"] = json.loads(data["score_breakdown_json"])
        except json.JSONDecodeError:
            data["score_breakdown"] = []
    else:
        data["score_breakdown"] = []
    data["is_spam"] = bool(data.get("is_spam"))
    data["created_ist"] = to_ist(data.get("created_at"))
    data["source_label"] = humanize_source(str(data.get("source") or ""))
    return data


def get_lead(conn: sqlite3.Connection, lead_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
    return row_to_dict(row)


def find_existing(conn: sqlite3.Connection, lead: dict[str, Any], dhash: str) -> sqlite3.Row | None:
    row = conn.execute("SELECT * FROM leads WHERE dedupe_hash = ?", (dhash,)).fetchone()
    if row:
        return row
    if lead.get("phone_e164"):
        row = conn.execute(
            "SELECT * FROM leads WHERE phone_e164 = ? ORDER BY created_at ASC LIMIT 1",
            (lead["phone_e164"],),
        ).fetchone()
        if row:
            return row
    if lead.get("email"):
        row = conn.execute(
            "SELECT * FROM leads WHERE email = ? ORDER BY created_at ASC LIMIT 1",
            (lead["email"],),
        ).fetchone()
    return row


def upsert_lead(conn: sqlite3.Connection, lead: dict[str, Any]) -> tuple[str, bool]:
    """Insert or merge a lead. Returns (lead_id, is_new)."""
    dhash = dedupe_hash(
        lead.get("phone_e164"),
        lead.get("email"),
        lead.get("source", ""),
        str(lead.get("source_external_id", "")),
    )
    existing = find_existing(conn, lead, dhash)
    now = iso_utc()

    if existing:
        lead_id = str(existing["lead_id"])
        same_submission = (
            existing["source"] == lead.get("source")
            and existing["source_external_id"] == lead.get("source_external_id")
        )
        updates: dict[str, Any] = {}
        for field in _MERGE_FIELDS:
            incoming = lead.get(field)
            if incoming in (None, "", "Not provided"):
                continue
            current = existing[field]
            # A genuine repeat enquiry carries newer requirement details; a
            # retry of the same submission only fills gaps.
            if not same_submission or current in (None, "", "Not provided") or field == "message":
                updates[field] = incoming
        if lead.get("budget_min") or lead.get("budget_max"):
            if lead.get("budget_min"):
                updates["budget_min"] = lead.get("budget_min")
            if lead.get("budget_max"):
                updates["budget_max"] = lead.get("budget_max")
            updates["budget_currency"] = lead.get("budget_currency", "INR")
        updates.update(
            {
                "updated_at": now,
                "source": lead.get("source") or existing["source"],
                "source_external_id": lead.get("source_external_id") or existing["source_external_id"],
                "raw_json": json.dumps(lead.get("raw", {}), ensure_ascii=False),
                "consent": int(bool(existing["consent"]) or bool(lead.get("consent"))),
                "touch_count": int(existing["touch_count"] or 1) + (0 if same_submission else 1),
            }
        )
        if not same_submission:
            updates["status"] = "New"
            updates["sla_flag"] = None
        assignments = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(
            f"UPDATE leads SET {assignments} WHERE lead_id = ?",
            [*updates.values(), lead_id],
        )
        # A genuine repeat enquiry is a new routing opportunity: re-run all steps.
        # A retry of the same submission resumes completed steps instead.
        if not same_submission:
            conn.execute("DELETE FROM lead_steps WHERE lead_id = ?", (lead_id,))
        conn.commit()
        return lead_id, False

    lead_id = uuid.uuid4().hex[:12].upper()
    row = {
        "lead_id": lead_id,
        "created_at": now,
        "updated_at": now,
        "source": lead.get("source"),
        "source_external_id": lead.get("source_external_id"),
        "name": lead.get("name"),
        "phone": lead.get("phone"),
        "phone_e164": lead.get("phone_e164"),
        "email": lead.get("email"),
        "property_type": lead.get("property_type"),
        "location": lead.get("location"),
        "budget_min": lead.get("budget_min"),
        "budget_max": lead.get("budget_max"),
        "budget_currency": lead.get("budget_currency") or "INR",
        "timeline": lead.get("timeline") or "Not provided",
        "timeline_days": lead.get("timeline_days"),
        "message": lead.get("message"),
        "preferred_language": lead.get("preferred_language"),
        "consent": int(bool(lead.get("consent"))),
        "raw_json": json.dumps(lead.get("raw", {}), ensure_ascii=False),
        "dedupe_hash": dhash,
        "touch_count": 1,
        "status": "New",
    }
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO leads ({columns}) VALUES ({placeholders})", list(row.values()))
    conn.commit()
    return lead_id, True


def update_lead(conn: sqlite3.Connection, lead_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = iso_utc()
    assignments = ", ".join(f"{column} = ?" for column in fields)
    conn.execute(f"UPDATE leads SET {assignments} WHERE lead_id = ?", [*fields.values(), lead_id])
    conn.commit()


def list_leads_for_date(
    conn: sqlite3.Connection,
    digest_date: str,
    tz_name: str = "Asia/Kolkata",
) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM leads ORDER BY created_at ASC").fetchall()
    result = []
    for row in rows:
        lead = row_to_dict(row)
        created = to_tz(lead.get("created_at"), tz_name)
        if created and created.strftime("%Y-%m-%d") == digest_date:
            result.append(lead)
    return result


def list_stale_leads(
    conn: sqlite3.Connection,
    tier: str,
    minutes: int,
    tz_name: str = "Asia/Kolkata",
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM leads
        WHERE tier = ? AND status = 'New' AND first_contact_at IS NULL
          AND sla_flag IS NULL
        """,
        (tier,),
    ).fetchall()
    now = now_utc()
    stale = []
    for row in rows:
        lead = row_to_dict(row)
        created = to_tz(lead.get("created_at"), tz_name)
        if created and (now - created).total_seconds() >= minutes * 60:
            stale.append(lead)
    return stale


def mark_step(
    conn: sqlite3.Connection,
    lead_id: str,
    step: str,
    status: str,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO lead_steps (lead_id, step, status, attempts, last_error, updated_at)
        VALUES (?, ?, ?, 1, ?, ?)
        ON CONFLICT(lead_id, step) DO UPDATE SET
            status = excluded.status,
            attempts = lead_steps.attempts + 1,
            last_error = excluded.last_error,
            updated_at = excluded.updated_at
        """,
        (lead_id, step, status, (error or "")[:1000] or None, iso_utc()),
    )
    conn.commit()


def step_done(conn: sqlite3.Connection, lead_id: str, step: str) -> bool:
    row = conn.execute(
        "SELECT status FROM lead_steps WHERE lead_id = ? AND step = ?",
        (lead_id, step),
    ).fetchone()
    return bool(row and row["status"] in ("done", "skipped"))


def reset_steps(conn: sqlite3.Connection, lead_id: str | None = None) -> int:
    if lead_id:
        cursor = conn.execute("DELETE FROM lead_steps WHERE lead_id = ?", (lead_id,))
    else:
        cursor = conn.execute("DELETE FROM lead_steps")
    conn.commit()
    return cursor.rowcount


def reset_failed_events(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "UPDATE events SET status = 'pending', attempts = 0, last_error = NULL WHERE status IN ('retry', 'dead', 'processing')"
    )
    conn.commit()
    return cursor.rowcount
