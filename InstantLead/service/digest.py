"""Build and deliver the daily sales digest."""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from tools.lib import drive, gmail, sheet
from tools.lib.config import Config, ConfigError
from tools.lib.db import digest_exists, record_digest
from tools.lib.email_render import render_digest_email
from tools.lib.facts import build_digest_facts, with_valid_logo
from tools.lib.leads import list_leads_for_date
from tools.lib.logging import log_info, log_warning, safe_exception
from tools.lib.pdf import render_digest_pdf


def digest_stats(leads: list[dict[str, Any]]) -> dict[str, Any]:
    tiers = Counter((lead.get("tier") or "COLD") for lead in leads)
    sources = Counter((lead.get("source_label") or lead.get("source") or "Unknown") for lead in leads)
    scored = [int(lead.get("score") or 0) for lead in leads]
    return {
        "total": len(leads),
        "hot": tiers.get("HOT", 0),
        "warm": tiers.get("WARM", 0),
        "cold": tiers.get("COLD", 0),
        "meetings": sum(1 for lead in leads if lead.get("calendar_event_id")),
        "uncontacted_hot": sum(
            1
            for lead in leads
            if lead.get("tier") == "HOT" and (lead.get("status") or "New") == "New"
        ),
        "avg_score": round(sum(scored) / len(scored)) if scored else 0,
        "sources": " · ".join(f"{name} {count}" for name, count in sources.most_common()) or "None",
    }


def send_daily_digest(
    conn: sqlite3.Connection,
    config: Config,
    digest_date: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    if not force and digest_exists(conn, digest_date):
        log_info("digest", "digest already sent; skipping", digest_date=digest_date)
        return {
            "digest_date": digest_date,
            "skipped": True,
            "reason": "already sent; use --force to resend",
        }
    leads = list_leads_for_date(conn, digest_date, config.business_tz)
    stats = digest_stats(leads)
    facts = with_valid_logo(build_digest_facts(leads, config, digest_date, stats), config)
    pdf_path = render_digest_pdf(facts, config)
    pdf_link = ""
    try:
        if config.drive_folder_id or config.dry_run:
            uploaded = drive.upload_file(
                pdf_path,
                config,
                filename=pdf_path.name,
                mimetype="application/pdf",
            )
            pdf_link = uploaded.get("webViewLink", "")
    except ConfigError as exc:
        log_warning("digest", "Drive archive skipped", error=safe_exception(exc))

    subject, html, text = render_digest_email(facts)
    message_id = gmail.send_digest_email(
        subject=subject,
        html=html,
        text=text,
        pdf_path=pdf_path,
        facts=facts,
        config=config,
    )

    if not config.dry_run and config.sheet_id:
        try:
            sheet.prepare_sheet(config)
            service = sheet._service(config)
            sheet.update_digest_tab(service, config, digest_date, stats, pdf_link)
        except Exception as exc:
            log_warning("digest", "could not update Digest tab", error=safe_exception(exc))

    record_digest(
        conn,
        digest_date=digest_date,
        total=stats["total"],
        hot=stats["hot"],
        warm=stats["warm"],
        cold=stats["cold"],
        pdf_path=str(pdf_path),
        pdf_drive_link=pdf_link,
        gmail_message_id=message_id,
    )
    log_info(
        "digest",
        "sent daily digest",
        digest_date=digest_date,
        total=stats["total"],
        hot=stats["hot"],
        message_id=message_id,
    )
    return {
        "digest_date": digest_date,
        "stats": stats,
        "pdf": str(pdf_path),
        "pdf_link": pdf_link,
        "message_id": message_id,
    }
