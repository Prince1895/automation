from __future__ import annotations

from dataclasses import replace

from service.digest import send_daily_digest
from service.pipeline import ingest_and_process
from service.pollers import check_sla
from tests.conftest import load_fixture
from tools.lib.db import connect, digest_exists
from tools.lib.leads import get_lead, list_stale_leads, step_done


def _ingest(conn, config, fixture: str, source: str = "form") -> dict:
    return ingest_and_process(
        conn,
        config,
        source=source,
        payload=load_fixture(fixture),
    )


def test_hot_lead_runs_full_dry_run_pipeline(config):
    conn = connect(config.db_path)
    try:
        result = _ingest(conn, config, "form_lead.json")
        assert result["duplicate"] is False
        assert len(result["leads"]) == 1
        lead = get_lead(conn, result["leads"][0])
        assert lead is not None
        assert lead["tier"] == "HOT"
        assert lead["score"] >= 70
        assert lead["status"] == "New"
        assert lead["pdf_drive_link"].startswith("file://")
        assert lead["meet_link"].startswith("https://meet.google.com/dry-")
        assert lead["gmail_message_id"].startswith("dry-")
        for step in ("scored", "pdf", "drive", "calendar", "sheet", "email"):
            assert step_done(conn, lead["lead_id"], step), step
        assert (config.outbox_dir / "sheet_rows.jsonl").exists()
        assert list(config.outbox_dir.glob("lead_*.eml"))
        assert list(config.archive_dir.glob("lead_*.pdf"))
    finally:
        conn.close()


def test_duplicate_event_is_idempotent(config):
    conn = connect(config.db_path)
    try:
        first = _ingest(conn, config, "form_lead.json")
        second = _ingest(conn, config, "form_lead.json")
        assert second["duplicate"] is True
        assert second["leads"] == first["leads"]
        lead = get_lead(conn, first["leads"][0])
        assert lead["touch_count"] == 1
    finally:
        conn.close()


def test_repeat_enquiry_merges_into_same_lead(config):
    conn = connect(config.db_path)
    try:
        first = _ingest(conn, config, "form_lead.json")
        second = _ingest(conn, config, "form_repeat.json")
        assert second["leads"][0] == first["leads"][0]
        lead = get_lead(conn, first["leads"][0])
        assert lead["touch_count"] == 2
        assert lead["property_type"] == "4BHK"
        assert "Andheri" in lead["location"]
        assert lead["tier"] == "WARM"
    finally:
        conn.close()


def test_spam_lead_is_quarantined_without_individual_email(config):
    conn = connect(config.db_path)
    try:
        result = _ingest(conn, config, "spam_form.json")
        lead = get_lead(conn, result["leads"][0])
        assert lead["status"] == "Spam"
        assert lead["is_spam"] is True
        assert not lead["pdf_local_path"]
        assert not list(config.outbox_dir.glob("lead_*.eml"))
    finally:
        conn.close()


def test_daily_digest_is_generated_and_recorded(config):
    conn = connect(config.db_path)
    try:
        _ingest(conn, config, "form_lead.json")
        _ingest(conn, config, "google_form_lead.json", source="google_form")
        lead = get_lead(conn, conn.execute("SELECT lead_id FROM leads LIMIT 1").fetchone()["lead_id"])
        digest_date = lead["created_ist"].strftime("%Y-%m-%d")
        result = send_daily_digest(conn, config, digest_date)
        assert result["stats"]["total"] == 2
        assert result["stats"]["hot"] >= 1
        assert result["stats"]["warm"] >= 1
        assert digest_exists(conn, digest_date)
        assert (config.outbox_dir / f"digest_{digest_date}.eml").exists()
        assert list(config.archive_dir.glob("InstantLead_Digest_*.pdf"))
        skipped = send_daily_digest(conn, config, digest_date)
        assert skipped["skipped"] is True
        forced = send_daily_digest(conn, config, digest_date, force=True)
        assert forced["stats"]["total"] == 2
    finally:
        conn.close()


def test_sla_alerts_once_for_uncontacted_hot_lead(config):
    conn = connect(config.db_path)
    try:
        _ingest(conn, config, "form_lead.json")
        stale = list_stale_leads(conn, "HOT", 0)
        assert len(stale) == 1
        sla_config = replace(config, hot_sla_minutes=0, warm_sla_minutes=0)
        first = check_sla(conn, sla_config)
        assert first["alerts"] == 1
        assert get_lead(conn, stale[0]["lead_id"])["sla_flag"].startswith("alerted:")
        second = check_sla(conn, sla_config)
        assert second["alerts"] == 0
    finally:
        conn.close()


def test_sheet_sanitizes_lead_values_and_phone_is_plain_text(config, tmp_path, monkeypatch):
    from tools.lib import sheet
    import json

    class FakeValues:
        def get(self, **kwargs):
            class R:
                def execute(self_inner):
                    return {"values": []}
            return R()

        def update(self, **kwargs):
            class R:
                def execute(self_inner):
                    return {}
            return R()

        def append(self, **kwargs):
            class R:
                def execute(self_inner):
                    return {"updates": {"updatedRange": "'Leads'!A10:Y10"}}
            return R()

    class FakeSpreadsheets:
        def values(self):
            return FakeValues()

        def batchUpdate(self, **kwargs):
            class R:
                def execute(self_inner):
                    return {}
            return R()

        def get(self, **kwargs):
            class R:
                def execute(self_inner):
                    return {"sheets": [{"properties": {"title": config.sheet_tab, "sheetId": 0}}]}
            return R()

    class FakeService:
        def spreadsheets(self):
            return FakeSpreadsheets()

    captured = {}

    def fake_append(self, spreadsheetId=None, range=None, valueInputOption=None, insertDataOption=None, body=None):
        captured["append_body"] = body
        class R:
            def execute(self_inner):
                return {"updates": {"updatedRange": "'Leads'!A10:Y10"}}
        return R()

    def fake_update(self, spreadsheetId=None, range=None, valueInputOption=None, body=None):
        captured["update_body"] = body
        class R:
            def execute(self_inner):
                return {}
        return R()

    def fake_get(self, spreadsheetId=None, range=None):
        class R:
            def execute(self_inner):
                if "!A2:A" in range:
                    return {"values": []}
                if "!A1:" in range and range.endswith("1"):
                    return {"values": [["Lead ID"]]}  # headers exist
                return {"values": []}
        return R()

    FakeValues.append = fake_append
    FakeValues.update = fake_update
    FakeValues.get = fake_get

    monkeypatch.setattr(sheet, "_service", lambda c: FakeService())

    lead = {
        "lead_id": "L1",
        "created_at": "2026-10-23T14:32:00+05:30",
        "tier": "HOT",
        "score": 90,
        "name": "=HYPERLINK(\"http://evil.com\",\"x\")",
        "phone": "+91 98765 43210",
        "phone_e164": "+919876543210",
        "email": "test@example.com",
        "property_type": "+cmd|'/c calc'!A0",
        "location": "@SUM(1+1)",
        "budget_min": 10000000,
        "budget_max": 15000000,
        "budget_currency": "INR",
        "timeline": "Within 30 days",
        "source_label": "Website Form",
        "status": "New",
        "owner": "",
        "message": "Hello",
        "score_reasons": [],
        "calendar_start": None,
        "meet_link": "",
        "pdf_drive_link": "",
        "gmail_message_id": "",
        "updated_at": "2026-10-23T14:32:00+05:30",
        "consent": True,
        "sla_flag": "",
        "touch_count": 1,
        "first_contact_at": None,
    }

    sheet.upsert_lead(FakeService(), lead, config)
    row = captured["append_body"]["values"][0]
    # Phone should remain as plain text/string as provided (not formula)
    assert row[5] == lead.get("phone") or row[5] == lead.get("phone_e164")
    assert not str(row[4]).startswith("=")
    assert not str(row[4]).startswith("+")
    assert not str(row[4]).startswith("@")
    assert not str(row[7]).startswith("=")
    assert not str(row[7]).startswith("+")
    assert not str(row[8]).startswith("@")
    # All values should be sanitized strings
    for i, v in enumerate(row):
        if isinstance(v, str) and (v.startswith('=') or v.startswith('@')):
            raise AssertionError(f"Unsanitized formula at col {i}: {v}")


def test_two_leads_cannot_get_same_calendar_slot_including_concurrent(config, monkeypatch):
    from tools.lib import calendar
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import threading

    tz = ZoneInfo(config.business_tz)
    # Fix "now"
    base = datetime(2026, 10, 26, 9, 0, tzinfo=tz)  # Monday
    monkeypatch.setattr(calendar, "datetime", type("DT", (), {
        "now": staticmethod(lambda tzinfo=None: base),
        "combine": datetime.combine,
    }))

    created = []
    lock = threading.Lock()

    def fake_events(service, config, start, end):
        return []

    monkeypatch.setattr(calendar, "_events", fake_events)

    real_insert = calendar.get_service

    class FakeEvents:
        def __init__(self):
            self.calls = 0
        def insert(self, calendarId=None, body=None, conferenceDataVersion=None, sendUpdates=None):
            class Exec:
                def execute(self_inner):
                    with lock:
                        created.append(body["start"]["dateTime"])
                        if len(created) > 1 and created[0] == created[-1]:
                            raise Exception("DOUBLE_BOOKING")
                    # Simulate slight delay for concurrency
                    import time
                    time.sleep(0.01)
                    return {
                        "id": f"evt-{len(created)}",
                        "start": body["start"],
                        "conferenceData": {"entryPoints": [{"entryPointType": "video", "uri": "https://meet.google.com/abc"}]},
                    }
            return Exec()

    class FakeCalService:
        def events(self):
            return FakeEvents()

    results = []
    errors = []

    def book():
        try:
            res = calendar.create_event({"lead_id": f"L{threading.get_ident()}", "tier": "HOT"}, {"name": "X", "property_type": "3BHK", "location": "P", "budget": "1 Cr", "timeline": "30d", "source": "web", "reasons": ["r"], "links": {}}, config, service=FakeCalService())
            results.append(res)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=book) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All should succeed but must get different start times (no double booking)
    assert len(results) >= 2
    starts = [r["start"] for r in results]
    assert len(starts) == len(set(starts))
