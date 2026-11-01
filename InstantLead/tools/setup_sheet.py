#!/usr/bin/env python3
"""Create/configure the Google Sheet and tabs used by InstantLead.

Purpose: one-shot setup for the team-facing tracker and digest tab.
Inputs: --create (create a new spreadsheet) or relies on SHEET_ID
Outputs: Sheet URL and tab names.
Example: python3 tools/setup_sheet.py --create
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib import sheet
from tools.lib.config import get_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare the InstantLead Google Sheet")
    parser.add_argument("--create", action="store_true", help="Create a new spreadsheet")
    parser.add_argument("--title", default="InstantLead – Leads")
    args = parser.parse_args()

    cfg = get_config()
    if args.create:
        result = sheet.create_spreadsheet(cfg, args.title)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    result = sheet.prepare_sheet(cfg)
    print(json.dumps({**result, "url": cfg.sheet_url}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
