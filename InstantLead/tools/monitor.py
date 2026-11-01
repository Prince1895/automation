#!/usr/bin/env python3
"""Check /healthz and the dead-letter queue, sending alerts on failure.

Purpose: run operational checks from cron, the scheduler, or a container
sidecar. Alerts go to ALERT_WEBHOOK_URL or ALERT_EMAILS/SALES_EMAILS.
Inputs: --json for machine-readable output; --no-send to evaluate only.
Outputs: JSON with health, dead-letter count, and alerts sent.
Example: python3 tools/monitor.py
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib.alerts import check_and_alert, check_healthz
from tools.lib.config import get_config
from tools.lib.db import connect, init_db, queue_counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Check InstantLead health and dead-letter queue")
    parser.add_argument("--no-send", action="store_true", help="Evaluate without notifying")
    args = parser.parse_args()

    cfg = get_config()
    init_db(cfg.db_path)
    conn = connect(cfg.db_path)
    try:
        if args.no_send:
            health = check_healthz(cfg)
            result = {
                "ok": health["ok"],
                "healthz": health,
                "dead_letter": int(queue_counts(conn).get("dead", 0)),
            }
        else:
            result = check_and_alert(conn, cfg)
            result["ok"] = bool(result["healthz"].get("ok"))
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
