#!/usr/bin/env python3
"""Replay failed or dead-lettered events.

Purpose: reset retry/dead events back to pending so the worker can reprocess them.
Inputs: --event-id <id> (single) or all failed
Outputs: count reset.
Example: python3 tools/replay_failed.py
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib.config import get_config
from tools.lib.db import connect, reset_event
from tools.lib.leads import reset_failed_events


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay failed events")
    parser.add_argument("--event-id", type=int)
    args = parser.parse_args()

    cfg = get_config()
    conn = connect(cfg.db_path)
    try:
        if args.event_id:
            reset_event(conn, args.event_id)
            print(json.dumps({"ok": True, "event_id": args.event_id, "reset": 1}))
            return 0
        count = reset_failed_events(conn)
        print(json.dumps({"ok": True, "reset": count}))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
