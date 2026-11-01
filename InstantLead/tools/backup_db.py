#!/usr/bin/env python3
"""Create a verified SQLite backup.

Purpose: take a consistent online backup (WAL-safe) and prune old copies.
Inputs: --out optional destination path; --no-verify to skip integrity check.
Outputs: JSON summary with path, size and integrity result.
Example: python3 tools/backup_db.py
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib.backup import backup_database
from tools.lib.config import get_config
from tools.lib.db import init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Back up the InstantLead SQLite database")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()

    cfg = get_config()
    init_db(cfg.db_path)
    result = backup_database(cfg, args.out, verify=not args.no_verify)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
