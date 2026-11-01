#!/usr/bin/env python3
"""Ingest a lead directly from a fixture/payload (no HTTP required).

Purpose: run the full pipeline against a local payload for testing.
Inputs: --source {form,google_form,whatsapp,instagram,email}, --file payload.json
Outputs: JSON result with lead_id and queue status.
Example: python3 tools/ingest_lead.py --source form --file tests/fixtures/form_lead.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.pipeline import ingest_and_process
from tools.lib.config import get_config
from tools.lib.db import connect, init_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a single lead payload")
    parser.add_argument("--source", required=True, choices=["form", "google_form", "whatsapp", "instagram", "email"])
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    cfg = get_config()
    init_db(cfg.db_path)
    payload = json.loads(args.file.read_text(encoding="utf-8"))
    conn = connect(cfg.db_path)
    try:
        result = ingest_and_process(conn, cfg, source=args.source, payload=payload, force=args.force)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
