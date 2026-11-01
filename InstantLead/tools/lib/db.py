"""SQLite schema and queue helpers.

SQLite is the source of truth; Google Sheets is a team-facing mirror. Events
are queued before processing so webhook retries and API outages cannot lose a
lead.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config, get_config
from .util import iso_utc, now_utc

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    received_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    lead_id TEXT,
    processed_at TEXT,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status, event_id);

CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL,
    source_external_id TEXT,
    name TEXT,
    phone TEXT,
    phone_e164 TEXT,
    email TEXT,
    property_type TEXT,
    location TEXT,
    budget_min INTEGER,
    budget_max INTEGER,
    budget_currency TEXT DEFAULT 'INR',
    timeline TEXT,
    timeline_days INTEGER,
    message TEXT,
    preferred_language TEXT,
    consent INTEGER NOT NULL DEFAULT 0,
    raw_json TEXT,
    dedupe_hash TEXT NOT NULL,
    touch_count INTEGER NOT NULL DEFAULT 1,
    score INTEGER,
    tier TEXT,
    is_spam INTEGER NOT NULL DEFAULT 0,
    score_reasons_json TEXT,
    score_breakdown_json TEXT,
    llm_json TEXT,
    status TEXT NOT NULL DEFAULT 'New',
    owner TEXT,
    assigned_at TEXT,
    first_contact_at TEXT,
    calendar_event_id TEXT,
    calendar_start TEXT,
    meet_link TEXT,
    pdf_local_path TEXT,
    pdf_drive_link TEXT,
    sheet_row INTEGER,
    gmail_message_id TEXT,
    digest_date TEXT,
    sla_flag TEXT,
    first_reply_at TEXT,
    first_reply_seconds INTEGER,
    first_reply_status TEXT,
    UNIQUE(dedupe_hash)
);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads(phone_e164);
CREATE INDEX IF NOT EXISTS idx_leads_email ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);
CREATE INDEX IF NOT EXISTS idx_leads_tier ON leads(tier, status);

CREATE TABLE IF NOT EXISTS lead_steps (
    lead_id TEXT NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (lead_id, step)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_name TEXT PRIMARY KEY,
    last_run_at TEXT,
    last_status TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS digests (
    digest_date TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    total INTEGER NOT NULL,
    hot INTEGER NOT NULL,
    warm INTEGER NOT NULL,
    cold INTEGER NOT NULL,
    pdf_path TEXT,
    pdf_drive_link TEXT,
    gmail_message_id TEXT
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT,
    model TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    cost_usd REAL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS first_replies (
    reply_id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    channel TEXT NOT NULL,
    to_address TEXT,
    subject TEXT NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    drafted_at TEXT NOT NULL,
    draft_seconds INTEGER,
    approved_at TEXT,
    sent_at TEXT,
    response_seconds INTEGER,
    decided_by TEXT,
    gmail_message_id TEXT,
    UNIQUE(lead_id)
);
CREATE INDEX IF NOT EXISTS idx_first_replies_status ON first_replies(status, reply_id);

CREATE TABLE IF NOT EXISTS alert_state (
    alert_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    detail TEXT,
    last_notified_at TEXT,
    updated_at TEXT NOT NULL
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    cfg = get_config()
    db_path = path or cfg.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Add columns introduced after the first release (idempotent)."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
    additions = {
        "first_reply_at": "TEXT",
        "first_reply_seconds": "INTEGER",
        "first_reply_status": "TEXT",
    }
    for column, column_type in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE leads ADD COLUMN {column} {column_type}")


def init_db(path: Path | None = None) -> Path:
    cfg = get_config()
    db_path = path or cfg.db_path
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
        conn.commit()
    finally:
        conn.close()
    return db_path


def create_event(
    conn: sqlite3.Connection,
    *,
    source: str,
    external_id: str,
    payload: dict[str, Any] | list[Any],
    received_at: str | None = None,
) -> tuple[int, bool]:
    """Insert an event idempotently. Returns (event_id, created)."""
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO events (source, external_id, received_at, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        (source, external_id, received_at or iso_utc(), json.dumps(payload, ensure_ascii=False)),
    )
    conn.commit()
    created = cursor.rowcount > 0
    row = conn.execute(
        "SELECT event_id FROM events WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()
    return int(row["event_id"]), created


def get_event(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()


def claim_event(conn: sqlite3.Connection, max_attempts: int) -> sqlite3.Row | None:
    """Atomically claim the next pending event."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM events
            WHERE status IN ('pending', 'retry') AND attempts < ?
            ORDER BY event_id LIMIT 1
            """,
            (max_attempts,),
        ).fetchone()
        if row is None:
            conn.commit()
            return None
        conn.execute(
            "UPDATE events SET status = 'processing', attempts = attempts + 1 WHERE event_id = ?",
            (row["event_id"],),
        )
        conn.commit()
        return get_event(conn, int(row["event_id"]))
    except Exception:
        conn.rollback()
        raise


def mark_event_done(conn: sqlite3.Connection, event_id: int, lead_id: str | None = None) -> None:
    conn.execute(
        "UPDATE events SET status = 'done', lead_id = ?, processed_at = ?, last_error = NULL WHERE event_id = ?",
        (lead_id, iso_utc(), event_id),
    )
    conn.commit()


def mark_event_retry(
    conn: sqlite3.Connection,
    event_id: int,
    error: str,
    *,
    max_attempts: int,
) -> str:
    row = get_event(conn, event_id)
    attempts = int(row["attempts"]) if row else max_attempts
    status = "dead" if attempts >= max_attempts else "retry"
    conn.execute(
        "UPDATE events SET status = ?, last_error = ? WHERE event_id = ?",
        (status, error[:1000], event_id),
    )
    conn.commit()
    return status


def reset_event(conn: sqlite3.Connection, event_id: int) -> None:
    conn.execute(
        "UPDATE events SET status = 'pending', attempts = 0, last_error = NULL WHERE event_id = ?",
        (event_id,),
    )
    conn.commit()


def queue_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) AS count FROM events GROUP BY status").fetchall()
    return {row["status"]: int(row["count"]) for row in rows}


def job_last_run(conn: sqlite3.Connection, name: str) -> datetime | None:
    row = conn.execute("SELECT last_run_at FROM jobs WHERE job_name = ?", (name,)).fetchone()
    if not row or not row["last_run_at"]:
        return None
    try:
        return datetime.fromisoformat(row["last_run_at"])
    except ValueError:
        return None


def set_job_run(conn: sqlite3.Connection, name: str, status: str, error: str | None = None) -> None:
    conn.execute(
        """
        INSERT INTO jobs (job_name, last_run_at, last_status, last_error)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(job_name) DO UPDATE SET
            last_run_at = excluded.last_run_at,
            last_status = excluded.last_status,
            last_error = excluded.last_error
        """,
        (name, iso_utc(), status, (error or "")[:1000] or None),
    )
    conn.commit()


def digest_exists(conn: sqlite3.Connection, digest_date: str) -> bool:
    return conn.execute("SELECT 1 FROM digests WHERE digest_date = ?", (digest_date,)).fetchone() is not None


def record_digest(conn: sqlite3.Connection, **fields: Any) -> None:
    conn.execute(
        """
        INSERT INTO digests (digest_date, created_at, total, hot, warm, cold, pdf_path, pdf_drive_link, gmail_message_id)
        VALUES (:digest_date, :created_at, :total, :hot, :warm, :cold, :pdf_path, :pdf_drive_link, :gmail_message_id)
        ON CONFLICT(digest_date) DO UPDATE SET
            created_at = excluded.created_at,
            total = excluded.total, hot = excluded.hot, warm = excluded.warm, cold = excluded.cold,
            pdf_path = excluded.pdf_path, pdf_drive_link = excluded.pdf_drive_link,
            gmail_message_id = excluded.gmail_message_id
        """,
        {
            "created_at": iso_utc(),
            "pdf_path": None,
            "pdf_drive_link": None,
            "gmail_message_id": None,
            **fields,
        },
    )
    conn.commit()


def prune_old_events(conn: sqlite3.Connection, retention_days: int) -> int:
    cutoff = now_utc().timestamp() - retention_days * 86400
    rows = conn.execute("SELECT event_id, received_at FROM events WHERE status = 'done'").fetchall()
    stale = []
    for row in rows:
        try:
            if datetime.fromisoformat(row["received_at"]).timestamp() < cutoff:
                stale.append(int(row["event_id"]))
        except ValueError:
            continue
    for event_id in stale:
        conn.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
    conn.commit()
    return len(stale)


def event_exists(conn: sqlite3.Connection, source: str, external_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM events WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()
    return row is not None
