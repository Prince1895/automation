#!/usr/bin/env python3
"""Generate a lead PDF from an existing lead or a facts JSON file.

Purpose: render the branded A4 brief and digest.
Inputs: --lead-id <id> (DB lookup) or --facts <facts.json>
Outputs: path to the generated PDF.
Example: python3 tools/generate_pdf.py --lead-id A1B2C3D4E5F6
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.lib.config import get_config
from tools.lib.db import connect
from tools.lib.facts import build_lead_facts, build_digest_facts, with_valid_logo
from tools.lib.leads import get_lead, list_leads_for_date
from tools.lib.pdf import render_digest_pdf, render_lead_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description="Render branded PDFs")
    parser.add_argument("--lead-id")
    parser.add_argument("--facts")
    parser.add_argument("--digest-date")
    args = parser.parse_args()

    cfg = get_config()
    if args.facts:
        facts = json.loads(Path(args.facts).read_text(encoding="utf-8"))
        facts = with_valid_logo(facts, cfg)
        path = render_digest_pdf(facts, cfg) if facts.get("digest_date") else render_lead_pdf(facts, cfg)
        print(json.dumps({"ok": True, "pdf": str(path)}))
        return 0

    conn = connect(cfg.db_path)
    try:
        if args.lead_id:
            lead = get_lead(conn, args.lead_id)
            if not lead:
                raise SystemExit(f"Lead not found: {args.lead_id}")
            facts = with_valid_logo(build_lead_facts(lead, cfg), cfg)
            path = render_lead_pdf(facts, cfg)
            print(json.dumps({"ok": True, "lead_id": args.lead_id, "pdf": str(path)}))
            return 0
        if args.digest_date:
            leads = list_leads_for_date(conn, args.digest_date, cfg.business_tz)
            from service.digest import digest_stats

            stats = digest_stats(leads)
            facts = with_valid_logo(build_digest_facts(leads, cfg, args.digest_date, stats), cfg)
            path = render_digest_pdf(facts, cfg)
            print(json.dumps({"ok": True, "digest_date": args.digest_date, "pdf": str(path), "count": len(leads)}))
            return 0
    finally:
        conn.close()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
