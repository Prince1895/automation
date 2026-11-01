#!/usr/bin/env python3
"""Report queue depth and job status.

Purpose: quick operational view.
Inputs: none
Outputs: JSON snapshot.
Example: python3 tools/queue_status.py
"""

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib.config import get_config
from tools.lib.db import connect


def main() -> int:
    cfg = get_config()
    conn = connect(cfg.db_path)
    conn.row_factory = sqlite3.Row
    try:
        events = {row["status"]: row["count"] for row in conn.execute("SELECT status, COUNT(*) AS count FROM events GROUP BY status")}
        jobs = [dict(row) for row in conn.execute("SELECT * FROM jobs ORDER BY job_name")]
        leads = {row["tier"] or "UNSCORED": row["count"] for row in conn.execute("SELECT tier, COUNT(*) AS count FROM leads GROUP BY tier")}
        spam = conn.execute("SELECT COUNT(*) AS c FROM leads WHERE is_spam = 1").fetchone()["c"]
        print(json.dumps({"events": events, "jobs": jobs, "leads_by_tier": leads, "spam": spam}, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
