#!/usr/bin/env python3
"""Check for HOT/WARM leads that have breached their first-response SLA.

Purpose: send the SLA alert and mark leads so the alert is not repeated.
Inputs: none (reads HOT_SLA_MINUTES, WARM_SLA_MINUTES, SLA_ENABLED).
Outputs: JSON count of leads alerted.
Example: python3 tools/sla_check.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.pollers import check_sla
from tools.lib.config import get_config
from tools.lib.db import connect, init_db


def main() -> int:
    cfg = get_config()
    init_db(cfg.db_path)
    conn = connect(cfg.db_path)
    try:
        result = check_sla(conn, cfg)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
