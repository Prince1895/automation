#!/usr/bin/env python3
"""Send the daily digest for a given date.

Purpose: build PDF, archive to Drive, email sales, update the Sheet digest tab.
Inputs: --date YYYY-MM-DD (defaults to today in BUSINESS_TZ)
Outputs: JSON result.
Example: python3 tools/send_digest.py
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.digest import send_daily_digest
from tools.lib.config import get_config
from tools.lib.db import connect, init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Send the daily lead digest")
    parser.add_argument("--date")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = get_config()
    init_db(cfg.db_path)
    tz = ZoneInfo(cfg.business_tz)
    date = args.date or datetime.now(tz).strftime("%Y-%m-%d")
    conn = connect(cfg.db_path)
    try:
        result = send_daily_digest(conn, cfg, date, force=args.force)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
