#!/usr/bin/env python3
"""Load sample leads into an isolated demo database for a clean video run.

Purpose: reset a demo database, ingest labelled synthetic leads through the
full pipeline, approve a few first replies, and optionally build a digest.
Inputs: --count, --seed, --reset, --approve-replies, --digest, --live --yes.
Outputs: JSON summary and visible artifacts under .tmp/demo/.
Example: python3 tools/seed_demo.py --reset --approve-replies 3 --digest
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from service.digest import send_daily_digest
from service.pipeline import ingest_and_process
from tools.lib.config import BASE_DIR, get_config, reset_config_cache
from tools.lib.db import connect, init_db
from tools.lib.demo import generate_demo_leads
from tools.lib.leads import get_lead, update_lead
from tools.lib.replies import approve_first_reply, list_pending, reply_metrics
from tools.lib.util import iso_utc


def _safe_reset(path: Path, yes: bool) -> None:
    tmp_root = (BASE_DIR / ".tmp").resolve()
    if not path.resolve().is_relative_to(tmp_root) and not yes:
        raise SystemExit("Refusing to delete a database outside .tmp without --yes")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed an isolated InstantLead demo")
    parser.add_argument("--db", type=Path, default=BASE_DIR / ".tmp/demo/instantlead.db")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--approve-replies", type=int, default=3)
    parser.add_argument("--digest", action="store_true")
    parser.add_argument("--live", action="store_true", help="Use live credentials (requires --yes)")
    parser.add_argument("--yes", action="store_true")
    args = parser.parse_args()

    if args.live and not args.yes:
        parser.error("--live sends customer-facing replies; re-run with --yes")

    db = args.db if args.db.is_absolute() else BASE_DIR / args.db
    demo_root = db.parent
    archive = demo_root / "archive"
    outbox = demo_root / "outbox"
    logs = demo_root / "logs"
    backups = demo_root / "backups"

    if args.reset:
        _safe_reset(db, args.yes)
        for path in (db, Path(f"{db}-wal"), Path(f"{db}-shm")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        for directory in (archive, outbox, logs, backups):
            shutil.rmtree(directory, ignore_errors=True)

    os.environ.update(
        {
            "DB_PATH": str(db),
            "ARCHIVE_DIR": str(archive),
            "OUTBOX_DIR": str(outbox),
            "LOG_DIR": str(logs),
            "BACKUP_DIR": str(backups),
            "WORKER_ENABLED": "0",
            "SCHEDULER_ENABLED": "0",
            "BACKUP_ENABLED": "0",
            "ALERT_CHECK_ENABLED": "0",
        }
    )
    os.environ["DRY_RUN"] = "0" if args.live else "1"
    if not args.live:
        os.environ.setdefault("LLM_ENABLED", "0")
    reset_config_cache()

    cfg = get_config()
    cfg.ensure_dirs()
    init_db(cfg.db_path)

    records = generate_demo_leads(args.count, args.seed)
    conn = connect(cfg.db_path)
    try:
        lead_ids = []
        for record in records:
            result = ingest_and_process(
                conn,
                cfg,
                source=record["source"],
                payload=record["payload"],
                external_id=f"DEMO-{record['demo_index']:04d}",
            )
            lead_ids.extend(result["leads"])

        unique_ids = list(dict.fromkeys(lead_ids))
        if len(unique_ids) >= 3:
            update_lead(conn, unique_ids[1], status="Contacted", first_contact_at=iso_utc())
            update_lead(conn, unique_ids[2], status="Meeting Set", first_contact_at=iso_utc())

        approved = []
        for row in list_pending(conn, max(0, args.approve_replies)):
            reply = approve_first_reply(conn, row["lead_id"], cfg, actor="demo")
            approved.append(
                {
                    "lead_id": row["lead_id"],
                    "status": reply["status"],
                    "response_seconds": reply.get("response_seconds"),
                }
            )

        digest = None
        if args.digest:
            today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
            digest = send_daily_digest(conn, cfg, today)

        tiers: dict[str, int] = {}
        for lead_id in unique_ids:
            lead = get_lead(conn, lead_id)
            if lead:
                key = lead.get("tier") or "UNSCORED"
                tiers[key] = tiers.get(key, 0) + 1

        summary = {
            "ok": True,
            "dry_run": cfg.dry_run,
            "db": str(cfg.db_path),
            "leads": len(unique_ids),
            "tiers": tiers,
            "approved_replies": approved,
            "reply_metrics": reply_metrics(conn, cfg),
            "digest": digest,
            "artifacts": {
                "pdfs": str(cfg.archive_dir),
                "emails": str(cfg.outbox_dir),
                "logs": str(cfg.log_dir),
            },
        }
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
