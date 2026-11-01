#!/usr/bin/env python3
"""Process queued events once, without running the HTTP service.

Purpose: drain the intake queue from the CLI (cron, debugging, recovery).
Inputs: --max-events N (default 100)
Outputs: JSON counts of processed events and any errors.
Example: python3 tools/process_queue.py --max-events 10
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.pipeline import process_event
from tools.lib.config import get_config
from tools.lib.db import claim_event, connect, init_db, mark_event_done, mark_event_retry
from tools.lib.logging import log_error, log_info, safe_exception


def main() -> int:
    parser = argparse.ArgumentParser(description="Drain the InstantLead queue once")
    parser.add_argument("--max-events", type=int, default=100)
    args = parser.parse_args()

    cfg = get_config()
    init_db(cfg.db_path)
    conn = connect(cfg.db_path)
    processed = failed = 0
    errors: list[dict[str, object]] = []
    try:
        while processed + failed < args.max_events:
            event = claim_event(conn, cfg.max_event_attempts)
            if event is None:
                break
            event_id = int(event["event_id"])
            try:
                leads = process_event(conn, event, cfg)
                mark_event_done(conn, event_id, leads[0] if leads else None)
                processed += 1
            except Exception as exc:
                message = safe_exception(exc)
                status = mark_event_retry(
                    conn, event_id, message, max_attempts=cfg.max_event_attempts
                )
                failed += 1
                errors.append({"event_id": event_id, "status": status, "error": message})
                log_error("process_queue", "event failed", event_id=event_id, status=status)
        log_info("process_queue", "queue drain finished", processed=processed, failed=failed)
        print(json.dumps({"ok": failed == 0, "processed": processed, "failed": failed, "errors": errors}, ensure_ascii=False))
        return 0 if failed == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
