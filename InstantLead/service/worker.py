"""Background queue worker: claims events, runs the pipeline, retries safely."""

from __future__ import annotations

import threading
import time

from tools.lib.config import Config
from tools.lib.db import claim_event, connect, mark_event_done, mark_event_retry, prune_old_events
from tools.lib.logging import log_error, log_info, log_warning, safe_exception

from .pipeline import process_event


def run_worker(config: Config, stop_event: threading.Event) -> None:
    conn = connect(config.db_path)
    log_info("worker", "worker started")
    try:
        while not stop_event.is_set():
            event = claim_event(conn, config.max_event_attempts)
            if event is None:
                stop_event.wait(config.worker_poll_seconds)
                continue
            event_id = int(event["event_id"])
            try:
                leads = process_event(conn, event, config)
                mark_event_done(conn, event_id, leads[0] if leads else None)
                log_info("worker", "event done", event_id=event_id, leads=len(leads))
            except Exception as exc:
                message = safe_exception(exc)
                status = mark_event_retry(
                    conn,
                    event_id,
                    message,
                    max_attempts=config.max_event_attempts,
                )
                log_error(
                    "worker",
                    "event failed",
                    event_id=event_id,
                    status=status,
                    error=message,
                )
                if status == "dead":
                    log_warning("worker", "event moved to dead letter", event_id=event_id)
    finally:
        try:
            prune_old_events(conn, config.retention_days)
        except Exception:
            pass
        conn.close()
        log_info("worker", "worker stopped")


def start_worker(config: Config, stop_event: threading.Event) -> threading.Thread:
    thread = threading.Thread(
        target=run_worker,
        args=(config, stop_event),
        name="instantlead-worker",
        daemon=True,
    )
    thread.start()
    return thread


def main() -> None:
    """Run the worker standalone (no HTTP service)."""
    from tools.lib.config import get_config
    from tools.lib.db import init_db

    config = get_config()
    init_db(config.db_path)
    stop = threading.Event()
    try:
        run_worker(config, stop)
    except KeyboardInterrupt:
        stop.set()
        time.sleep(0.2)


if __name__ == "__main__":
    main()
