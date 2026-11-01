"""Lightweight scheduler for pollers, Sheet status sync, SLA checks and the digest."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from tools.lib.alerts import check_and_alert
from tools.lib.backup import backup_database
from tools.lib.config import Config
from tools.lib.db import connect, digest_exists, job_last_run, set_job_run
from tools.lib.logging import log_info, log_warning, safe_exception

from . import pollers
from .digest import send_daily_digest


def _due(conn, name: str, interval_seconds: int) -> bool:
    last = job_last_run(conn, name)
    return last is None or (datetime.now(last.tzinfo) - last).total_seconds() >= interval_seconds


def _run_job(conn, name: str, fn, *args) -> None:
    try:
        result = fn(*args)
        set_job_run(conn, name, "ok")
        log_info("scheduler", "job completed", job=name, result=result)
    except Exception as exc:
        message = safe_exception(exc)
        set_job_run(conn, name, "error", message)
        log_warning("scheduler", "job failed", job=name, error=message)


def _maybe_digest(conn, config: Config) -> None:
    if not config.digest_enabled:
        return
    tz = ZoneInfo(config.business_tz)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    hour, minute = config.digest_time
    if (now.hour, now.minute) < (hour, minute):
        return
    if digest_exists(conn, today):
        return
    _run_job(conn, "daily_digest", send_daily_digest, conn, config, today)


def _maybe_backup(conn, config: Config) -> None:
    if not config.backup_enabled:
        return
    if _due(conn, "db_backup", max(1, config.backup_interval_hours) * 3600):
        _run_job(conn, "db_backup", backup_database, config)


def run_scheduler(config: Config, stop_event: threading.Event) -> None:
    conn = connect(config.db_path)
    log_info("scheduler", "scheduler started")
    if config.alert_check_enabled and job_last_run(conn, "alert_check") is None:
        # Let the HTTP server finish binding before the first self-check.
        set_job_run(conn, "alert_check", "ok")
    try:
        while not stop_event.is_set():
            if config.forms_poll_enabled and _due(conn, "poll_forms", config.form_poll_seconds):
                _run_job(conn, "poll_forms", pollers.poll_forms, conn, config)
            if config.gmail_poll_enabled and _due(conn, "poll_email", config.email_poll_seconds):
                _run_job(conn, "poll_email", pollers.poll_email, conn, config)
            if _due(conn, "sync_statuses", config.status_sync_seconds):
                _run_job(conn, "sync_statuses", pollers.sync_statuses, conn, config)
            if config.sla_enabled and _due(conn, "sla_check", config.sla_check_seconds):
                _run_job(conn, "sla_check", pollers.check_sla, conn, config)
            if config.alert_check_enabled and _due(conn, "alert_check", config.alert_check_seconds):
                _run_job(conn, "alert_check", check_and_alert, conn, config)
            _maybe_backup(conn, config)
            _maybe_digest(conn, config)
            stop_event.wait(15)
    finally:
        conn.close()
        log_info("scheduler", "scheduler stopped")


def start_scheduler(config: Config, stop_event: threading.Event) -> threading.Thread:
    thread = threading.Thread(
        target=run_scheduler,
        args=(config, stop_event),
        name="instantlead-scheduler",
        daemon=True,
    )
    thread.start()
    return thread


def main() -> None:
    from tools.lib.config import get_config
    from tools.lib.db import init_db

    config = get_config()
    init_db(config.db_path)
    stop = threading.Event()
    try:
        run_scheduler(config, stop)
    except KeyboardInterrupt:
        stop.set()
        time.sleep(0.2)


if __name__ == "__main__":
    main()
