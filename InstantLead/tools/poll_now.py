#!/usr/bin/env python3
"""Poll Google Forms and/or the enquiry inbox immediately.

Purpose: run a poller on demand instead of waiting for the scheduler.
Inputs: --source forms|email|both (default: both)
Outputs: JSON counts of seen/queued records.
Example: python3 tools/poll_now.py --source email
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.pollers import poll_email, poll_forms
from tools.lib.config import get_config
from tools.lib.db import connect, init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Poll lead sources now")
    parser.add_argument("--source", choices=["forms", "email", "both"], default="both")
    args = parser.parse_args()

    cfg = get_config()
    init_db(cfg.db_path)
    conn = connect(cfg.db_path)
    result = {}
    try:
        if args.source in {"forms", "both"}:
            result["forms"] = poll_forms(conn, cfg)
        if args.source in {"email", "both"}:
            result["email"] = poll_email(conn, cfg)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
