#!/usr/bin/env python3
"""Manage approval-mode first replies.

Purpose: list pending drafts, approve/send them, reject them, and report the
measured time from lead creation to first response.
Inputs: subcommand list|approve|reject|stats; --lead-id for a single reply.
Outputs: JSON summary (personal data is masked in listings).
Example: python3 tools/reply.py list
         python3 tools/reply.py approve --lead-id ABC123 --yes
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib.config import get_config
from tools.lib.db import connect, init_db
from tools.lib.replies import (
    approve_first_reply,
    list_pending,
    mask_email,
    reject_first_reply,
    reply_metrics,
)


def _pending_row(reply: dict) -> dict:
    return {
        "lead_id": reply["lead_id"],
        "tier": reply.get("tier"),
        "score": reply.get("score"),
        "channel": reply["channel"],
        "to": mask_email(reply.get("to_address")),
        "drafted_at": reply["drafted_at"],
        "draft_seconds": reply.get("draft_seconds"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage approval-mode first replies")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="List pending drafts")
    listing.add_argument("--limit", type=int, default=50)

    approve = sub.add_parser("approve", help="Approve and send a draft")
    approve.add_argument("--lead-id")
    approve.add_argument("--all", action="store_true")
    approve.add_argument("--yes", action="store_true", help="Confirm customer-facing send")

    reject = sub.add_parser("reject", help="Reject a draft")
    reject.add_argument("--lead-id", required=True)
    reject.add_argument("--reason", default="")

    sub.add_parser("stats", help="Response-time metrics")

    args = parser.parse_args()
    cfg = get_config()
    init_db(cfg.db_path)
    conn = connect(cfg.db_path)
    try:
        if args.command == "list":
            rows = [_pending_row(row) for row in list_pending(conn, args.limit)]
            print(json.dumps({"ok": True, "pending": rows, "count": len(rows)}, ensure_ascii=False))
            return 0

        if args.command == "stats":
            print(json.dumps({"ok": True, "metrics": reply_metrics(conn, cfg)}, ensure_ascii=False))
            return 0

        if args.command == "approve":
            if not args.yes:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "Approval sends a customer-facing reply; re-run with --yes.",
                        }
                    )
                )
                return 2
            lead_ids: list[str] = []
            if args.all:
                lead_ids = [row["lead_id"] for row in list_pending(conn, 500)]
            elif args.lead_id:
                lead_ids = [args.lead_id]
            else:
                parser.error("approve requires --lead-id or --all")
            results = []
            for lead_id in lead_ids:
                reply = approve_first_reply(conn, lead_id, cfg, actor="cli")
                results.append(
                    {
                        "lead_id": lead_id,
                        "status": reply["status"],
                        "response_seconds": reply.get("response_seconds"),
                    }
                )
            print(json.dumps({"ok": True, "approved": results}, ensure_ascii=False))
            return 0

        if args.command == "reject":
            reply = reject_first_reply(conn, args.lead_id, cfg, reason=args.reason, actor="cli")
            print(json.dumps({"ok": True, "lead_id": args.lead_id, "status": reply["status"]}))
            return 0

        parser.error("unknown command")
        return 2
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
