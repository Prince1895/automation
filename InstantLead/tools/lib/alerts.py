"""Operational alerts for /healthz failures and dead-letter growth.

Alerts are sent to ALERT_WEBHOOK_URL when configured, otherwise to
ALERT_EMAILS/SALES_EMAILS (or a local .eml in dry-run mode). Repeated alerts
are suppressed by a cooldown so a persistent failure does not spam the team.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

import requests

from .config import Config
from .db import queue_counts
from .logging import log_info, log_warning, safe_exception
from .util import iso_utc, parse_datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _get_state(conn: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM alert_state WHERE alert_key = ?", (key,)).fetchone()
    return dict(row) if row else None


def _set_state(
    conn: sqlite3.Connection,
    key: str,
    status: str,
    detail: str,
    *,
    notified: bool,
) -> None:
    now = iso_utc()
    existing = _get_state(conn, key)
    last_notified = now if notified else (existing or {}).get("last_notified_at")
    conn.execute(
        """
        INSERT INTO alert_state (alert_key, status, detail, last_notified_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(alert_key) DO UPDATE SET
            status = excluded.status,
            detail = excluded.detail,
            last_notified_at = excluded.last_notified_at,
            updated_at = excluded.updated_at
        """,
        (key, status, detail[:500], last_notified, now),
    )
    conn.commit()


def _cooldown_elapsed(state: dict[str, Any] | None, minutes: int) -> bool:
    if not state or not state.get("last_notified_at"):
        return True
    last = parse_datetime(str(state["last_notified_at"]))
    if not last:
        return True
    return (_now() - last).total_seconds() >= minutes * 60


def send_alert_message(config: Config, subject: str, text: str) -> str:
    if config.alert_webhook_url:
        response = requests.post(
            config.alert_webhook_url,
            json={"text": f"*{subject}*\n{text}"},
            timeout=10,
        )
        response.raise_for_status()
        return "webhook"
    from .gmail import send_alert

    recipients = config.alert_emails or config.sales_emails
    html = (
        "<div style='font-family:Arial,sans-serif;color:#1c2833;'>"
        f"<h2 style='color:#C0392B;margin:0 0 8px;'>{subject}</h2>"
        f"<pre style='white-space:pre-wrap;font-size:13px;'>{text}</pre></div>"
    )
    return send_alert(subject, html, text, config, recipients=recipients)


def check_healthz(config: Config) -> dict[str, Any]:
    try:
        response = requests.get(config.healthz_url, timeout=10)
        payload: dict[str, Any] = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return {
            "ok": response.ok and bool(payload.get("ok", True)),
            "status_code": response.status_code,
            "payload": payload,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "status_code": None,
            "payload": {},
            "error": safe_exception(exc),
        }


def _notify(
    conn: sqlite3.Connection,
    config: Config,
    key: str,
    status: str,
    detail: str,
    subject: str,
    text: str,
) -> bool:
    try:
        channel = send_alert_message(config, subject, text)
    except Exception as exc:
        log_warning("alerts", "could not send alert", key=key, error=safe_exception(exc))
        _set_state(conn, key, status, detail, notified=False)
        return False
    _set_state(conn, key, status, detail, notified=True)
    log_info("alerts", "alert sent", key=key, channel=channel)
    return True


def check_and_alert(conn: sqlite3.Connection, config: Config) -> dict[str, Any]:
    """Run both checks, notifying on state changes or after the cooldown."""
    results: dict[str, Any] = {"healthz": {}, "dead_letter": {}, "sent": 0}

    health = check_healthz(config)
    health_state = _get_state(conn, "healthz")
    health_detail = health.get("error") or f"HTTP {health.get('status_code')}"
    results["healthz"] = {
        "ok": health["ok"],
        "status_code": health.get("status_code"),
        "detail": health_detail,
    }
    if not health["ok"]:
        should = (health_state or {}).get("status") != "failing" or _cooldown_elapsed(
            health_state, config.alert_cooldown_minutes
        )
        if should:
            sent = _notify(
                conn,
                config,
                "healthz",
                "failing",
                health_detail,
                "InstantLead /healthz is failing",
                f"Health check failed: {config.healthz_url}\nDetail: {health_detail}",
            )
            results["sent"] += int(sent)
    else:
        if (health_state or {}).get("status") == "failing":
            sent = _notify(
                conn,
                config,
                "healthz",
                "ok",
                "recovered",
                "InstantLead /healthz recovered",
                f"Health check is passing again: {config.healthz_url}",
            )
            results["sent"] += int(sent)
        else:
            _set_state(conn, "healthz", "ok", "healthy", notified=False)

    dead = int(queue_counts(conn).get("dead", 0))
    dead_state = _get_state(conn, "dead_letter")
    results["dead_letter"] = {
        "count": dead,
        "threshold": config.dead_letter_alert_threshold,
        "status": dead_state.get("status") if dead_state else "unknown",
    }
    threshold = max(1, int(config.dead_letter_alert_threshold))
    if dead >= threshold:
        should = (dead_state or {}).get("status") != "failing" or _cooldown_elapsed(
            dead_state, config.alert_cooldown_minutes
        )
        if should:
            sent = _notify(
                conn,
                config,
                "dead_letter",
                "failing",
                f"{dead} dead events",
                "InstantLead dead-letter queue is growing",
                f"Dead-letter events: {dead} (threshold {threshold}). "
                "Inspect with tools/queue_status.py and replay with tools/replay_failed.py.",
            )
            results["sent"] += int(sent)
    else:
        if (dead_state or {}).get("status") == "failing":
            sent = _notify(
                conn,
                config,
                "dead_letter",
                "ok",
                "drained",
                "InstantLead dead-letter queue recovered",
                f"Dead-letter events back below threshold: {dead} < {threshold}.",
            )
            results["sent"] += int(sent)
        else:
            _set_state(conn, "dead_letter", "ok", f"{dead} dead events", notified=False)

    return results


def alert_payload(config: Config, result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=True)
