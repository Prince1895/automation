#!/usr/bin/env python3
"""Initialise the InstantLead SQLite database.

Purpose: create the schema and required directories.
Inputs: none (reads .env/brand).
Outputs: path to the created database.
Example: python3 tools/init_db.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib.config import get_config
from tools.lib.db import init_db as _init_db
from tools.lib.logging import log_info


def main() -> int:
    cfg = get_config()
    path = _init_db(cfg.db_path)
    log_info("init_db", "database initialised", path=str(path))
    print(json.dumps({"ok": True, "db_path": str(path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
