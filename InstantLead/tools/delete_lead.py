#!/usr/bin/env python3
"""Erase a lead and its local personal data (GDPR-style request).

Purpose: delete by lead id, email or phone, including queue events, reply
drafts, step records, LLM usage and local PDF/email artifacts.
Inputs: --lead-id / --email / --phone, plus --yes to execute.
Outputs: JSON plan (without --yes) or deletion summary. Remote Google copies
are reported but must be removed with Google's own tooling.
Example: python3 tools/delete_lead.py --email person@example.com --yes
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib.config import get_config
from tools.lib.db import connect, init_db
from tools.lib.privacy import erase_leads, preview_erasure
from tools.lib.util import normalize_email, normalize_phone


def main() -> int:
    parser = argparse.ArgumentParser(description="Erase a lead and local personal data")
    parser.add_argument("--lead-id", action="append", default=[])
    parser.add_argument("--email", action="append", default=[])
    parser.add_argument("--phone", action="append", default=[])
    parser.add_argument("--keep-files", action="store_true", help="Keep local PDF/email files")
    parser.add_argument("--yes", action="store_true", help="Confirm irreversible deletion")
    args = parser.parse_args()

    if not (args.lead_id or args.email or args.phone):
        parser.error("provide at least one of --lead-id, --email or --phone")

    emails = [normalize_email(value) for value in args.email]
    phones = [normalize_phone(value)[1] for value in args.phone]
    emails = [value for value in emails if value]
    phones = [value for value in phones if value]

    cfg = get_config()
    init_db(cfg.db_path)
    conn = connect(cfg.db_path)
    try:
        filters = {"lead_ids": args.lead_id, "emails": emails, "phones": phones}
        if not args.yes:
            plan = preview_erasure(conn, **filters)
            plan["ok"] = True
            plan["dry_run"] = True
            plan["note"] = "Re-run with --yes to erase permanently."
            print(json.dumps(plan, ensure_ascii=False))
            return 0
        result = erase_leads(conn, cfg, delete_files=not args.keep_files, **filters)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
