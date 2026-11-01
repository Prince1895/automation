"""Lead pipeline orchestration shared by the worker, scheduler and CLI."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from tools.lib import calendar as calendar_tool
from tools.lib import drive, gmail, sheet
from tools.lib.config import Config
from tools.lib.db import create_event, get_event, mark_event_done
from tools.lib.email_render import render_lead_email
from tools.lib.facts import build_lead_facts, with_valid_logo
from tools.lib.leads import get_lead, mark_step, step_done, update_lead, upsert_lead
from tools.lib.llm import extract as llm_extract
from tools.lib.logging import log_info, log_warning, safe_exception
from tools.lib.normalize import extract_leads
from tools.lib.pdf import render_lead_pdf
from tools.lib.replies import draft_first_reply
from tools.lib.scoring import score_lead
from tools.lib.util import fmt_local, iso_utc


def _dry_run_sheet(lead: dict[str, Any], config: Config) -> None:
    config.outbox_dir.mkdir(parents=True, exist_ok=True)
    path = config.outbox_dir / "sheet_rows.jsonl"
    row = {
        "lead_id": lead.get("lead_id"),
        "created": fmt_local(lead.get("created_at"), config.business_tz),
        "tier": lead.get("tier"),
        "score": lead.get("score"),
        "name": lead.get("name"),
        "phone": lead.get("phone"),
        "email": lead.get("email"),
        "property_type": lead.get("property_type"),
        "location": lead.get("location"),
        "timeline": lead.get("timeline"),
        "source": lead.get("source_label"),
        "status": lead.get("status"),
        "pdf": lead.get("pdf_drive_link"),
        "meet": lead.get("meet_link"),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    path.chmod(0o600)


def _upsert_sheet(lead: dict[str, Any], config: Config) -> int:
    if config.dry_run:
        _dry_run_sheet(lead, config)
        return 0
    sheet.prepare_sheet(config)
    service = sheet._service(config)
    return sheet.upsert_lead(service, lead, config)


def _score_step(conn: sqlite3.Connection, lead: dict[str, Any], config: Config) -> dict[str, Any]:
    lead_id = str(lead["lead_id"])
    if step_done(conn, lead_id, "scored"):
        return get_lead(conn, lead_id) or lead
    llm = llm_extract(lead.get("message"), config)
    scored = score_lead(lead, config, llm)
    update_lead(
        conn,
        lead_id,
        score=scored.get("score"),
        tier=scored.get("tier"),
        is_spam=int(bool(scored.get("is_spam"))),
        score_reasons_json=json.dumps(scored.get("score_reasons", []), ensure_ascii=False),
        score_breakdown_json=json.dumps(scored.get("score_breakdown", []), ensure_ascii=False),
        llm_json=json.dumps(scored.get("llm", {}), ensure_ascii=False),
        budget_min=scored.get("budget_min"),
        budget_max=scored.get("budget_max"),
        budget_currency=scored.get("budget_currency") or "INR",
        timeline=scored.get("timeline") or "Not provided",
        timeline_days=scored.get("timeline_days"),
        property_type=scored.get("property_type"),
        location=scored.get("location"),
        preferred_language=scored.get("preferred_language"),
    )
    mark_step(conn, lead_id, "scored", "done")
    log_info(
        "pipeline",
        "scored lead",
        lead_id=lead_id,
        tier=scored.get("tier"),
        score=scored.get("score"),
    )
    return get_lead(conn, lead_id) or scored


def _ensure_pdf(conn: sqlite3.Connection, lead_id: str, config: Config) -> dict[str, Any]:
    lead = get_lead(conn, lead_id)
    if not lead:
        raise RuntimeError(f"Lead {lead_id} disappeared")
    if not step_done(conn, lead_id, "pdf"):
        facts = with_valid_logo(build_lead_facts(lead, config), config)
        path = render_lead_pdf(facts, config)
        update_lead(conn, lead_id, pdf_local_path=str(path))
        mark_step(conn, lead_id, "pdf", "done")
        log_info("pipeline", "rendered lead PDF", lead_id=lead_id, file=path.name)
    return get_lead(conn, lead_id) or lead


def _ensure_drive(conn: sqlite3.Connection, lead_id: str, config: Config) -> dict[str, Any]:
    lead = get_lead(conn, lead_id)
    if not lead:
        raise RuntimeError(f"Lead {lead_id} disappeared")
    if not step_done(conn, lead_id, "drive"):
        path = Path(lead.get("pdf_local_path") or "")
        if not path.exists():
            raise RuntimeError("PDF missing before Drive upload")
        result = drive.upload_pdf(path, lead, config)
        update_lead(conn, lead_id, pdf_drive_link=result.get("webViewLink", ""))
        mark_step(conn, lead_id, "drive", "done")
        log_info("pipeline", "archived PDF", lead_id=lead_id, drive_id=result.get("id"))
    return get_lead(conn, lead_id) or lead


def _ensure_calendar(conn: sqlite3.Connection, lead_id: str, config: Config) -> dict[str, Any]:
    lead = get_lead(conn, lead_id)
    if not lead:
        raise RuntimeError(f"Lead {lead_id} disappeared")
    if step_done(conn, lead_id, "calendar") or lead.get("meet_link"):
        return lead
    facts = with_valid_logo(build_lead_facts(lead, config), config)
    try:
        event = calendar_tool.create_event(lead, facts, config)
    except calendar_tool.NoSlotError as exc:
        mark_step(conn, lead_id, "calendar", "skipped", safe_exception(exc))
        log_warning("pipeline", "no calendar slot; lead still notified", lead_id=lead_id)
        return get_lead(conn, lead_id) or lead
    update_lead(
        conn,
        lead_id,
        calendar_event_id=event.get("event_id"),
        calendar_start=event.get("start"),
        meet_link=event.get("meet_link"),
    )
    mark_step(conn, lead_id, "calendar", "done")
    log_info("pipeline", "booked internal meeting", lead_id=lead_id, event_id=event.get("event_id"))
    return get_lead(conn, lead_id) or lead


def _ensure_sheet(conn: sqlite3.Connection, lead_id: str, config: Config) -> dict[str, Any]:
    lead = get_lead(conn, lead_id)
    if not lead:
        raise RuntimeError(f"Lead {lead_id} disappeared")
    if not step_done(conn, lead_id, "sheet"):
        row = _upsert_sheet(lead, config)
        update_lead(conn, lead_id, sheet_row=row or None)
        mark_step(conn, lead_id, "sheet", "done")
        log_info("pipeline", "mirrored lead to Sheet", lead_id=lead_id, row=row)
    return get_lead(conn, lead_id) or lead


def _ensure_email(conn: sqlite3.Connection, lead_id: str, config: Config) -> dict[str, Any]:
    lead = get_lead(conn, lead_id)
    if not lead:
        raise RuntimeError(f"Lead {lead_id} disappeared")
    if step_done(conn, lead_id, "email"):
        return lead
    facts = with_valid_logo(build_lead_facts(lead, config), config)
    subject, html, text = render_lead_email(facts)
    pdf_path = Path(lead.get("pdf_local_path") or "")
    if not pdf_path.exists():
        raise RuntimeError("PDF missing before email send")
    message_id = gmail.send_lead_email(
        subject=subject,
        html=html,
        text=text,
        pdf_path=pdf_path,
        facts=facts,
        config=config,
    )
    update_lead(conn, lead_id, gmail_message_id=message_id)
    mark_step(conn, lead_id, "email", "done")
    log_info("pipeline", "notified sales", lead_id=lead_id, message_id=message_id)
    return get_lead(conn, lead_id) or lead


def run_lead_pipeline(conn: sqlite3.Connection, lead_id: str, config: Config) -> dict[str, Any]:
    lead = get_lead(conn, lead_id)
    if not lead:
        raise RuntimeError(f"Unknown lead {lead_id}")
    lead = _score_step(conn, lead, config)

    if lead.get("is_spam") or (lead.get("status") or "").lower() == "spam":
        update_lead(conn, lead_id, status="Spam")
        _ensure_sheet(conn, lead_id, config)
        log_info("pipeline", "quarantined spam lead", lead_id=lead_id)
        return get_lead(conn, lead_id) or lead

    tier = lead.get("tier")
    notify = tier in {"HOT", "WARM"} or (tier == "COLD" and config.cold_email_enabled)
    if notify:
        _ensure_pdf(conn, lead_id, config)
        _ensure_drive(conn, lead_id, config)
        if tier in {"HOT", "WARM"}:
            _ensure_calendar(conn, lead_id, config)
        _ensure_sheet(conn, lead_id, config)
        _ensure_email(conn, lead_id, config)
    else:
        _ensure_sheet(conn, lead_id, config)

    updated = get_lead(conn, lead_id) or lead
    draft_first_reply(conn, updated, config)
    return get_lead(conn, lead_id) or updated


def process_event(conn: sqlite3.Connection, event: sqlite3.Row, config: Config) -> list[str]:
    payload = json.loads(event["payload_json"])
    leads = extract_leads(str(event["source"]), payload, event["received_at"])
    if not leads:
        log_warning("pipeline", "event contained no leads", event_id=event["event_id"])
        return []
    processed: list[str] = []
    for canonical in leads:
        if (
            (canonical.get("budget_min") or canonical.get("budget_max"))
            and (canonical.get("budget_currency") or "INR").upper() == "INR"
            and config.currency.upper() != "INR"
        ):
            canonical["budget_currency"] = config.currency.upper()
        lead_id, is_new = upsert_lead(conn, canonical)
        run_lead_pipeline(conn, lead_id, config)
        processed.append(lead_id)
        log_info(
            "pipeline",
            "processed lead",
            lead_id=lead_id,
            source=canonical.get("source"),
            is_new=is_new,
        )
    return processed


def ingest_and_process(
    conn: sqlite3.Connection,
    config: Config,
    *,
    source: str,
    payload: dict[str, Any],
    external_id: str | None = None,
    received_at: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if not external_id:
        external_id = str(
            payload.get("id")
            or payload.get("message_id")
            or payload.get("response_id")
            or iso_utc()
        )
    event_id, created = create_event(
        conn,
        source=source,
        external_id=external_id,
        payload=payload,
        received_at=received_at,
    )
    if not created and not force:
        event = get_event(conn, event_id)
        return {
            "event_id": event_id,
            "duplicate": True,
            "status": event["status"] if event else "unknown",
            "leads": [event["lead_id"]] if event and event["lead_id"] else [],
        }
    event = get_event(conn, event_id)
    assert event is not None
    leads = process_event(conn, event, config)
    mark_event_done(conn, event_id, leads[0] if leads else None)
    return {"event_id": event_id, "duplicate": False, "leads": leads}
