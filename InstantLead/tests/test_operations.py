from __future__ import annotations

import json
import stat
from dataclasses import replace

from service.pipeline import ingest_and_process
from tests.conftest import load_fixture
from tools.lib import alerts
from tools.lib.backup import backup_database
from tools.lib.config import get_config, reset_config_cache
from tools.lib.db import connect, create_event, init_db
from tools.lib.demo import generate_demo_leads
from tools.lib.leads import get_lead
from tools.lib.privacy import erase_leads, preview_erasure
from tools.lib.replies import (
    approve_first_reply,
    get_reply,
    list_pending,
    reject_first_reply,
    reply_metrics,
)


def _ingest(conn, config, fixture: str = "form_lead.json"):
    return ingest_and_process(
        conn, config, source="form", payload=load_fixture(fixture)
    )


def test_first_reply_draft_approval_and_metrics(config):
    conn = connect(config.db_path)
    try:
        result = _ingest(conn, config)
        lead_id = result["leads"][0]
        draft = get_reply(conn, lead_id)
        assert draft is not None
        assert draft["status"] == "draft"
        assert draft["channel"] == "email"
        assert get_lead(conn, lead_id)["first_reply_status"] == "pending"
        assert len(list_pending(conn)) == 1

        sent = approve_first_reply(conn, lead_id, config, actor="test")
        assert sent["status"] == "sent"
        assert sent["response_seconds"] >= 0
        assert sent["gmail_message_id"].startswith("dry-")
        assert get_lead(conn, lead_id)["first_reply_status"] == "sent"
        metrics = reply_metrics(conn, config)
        assert metrics["sent"] == 1
        assert metrics["pending"] == 0
        assert metrics["within_sla"] == 1
    finally:
        conn.close()


def test_first_reply_reject_and_off_mode(config):
    conn = connect(config.db_path)
    try:
        result = _ingest(conn, config)
        lead_id = result["leads"][0]
        rejected = reject_first_reply(conn, lead_id, config, reason="test")
        assert rejected["status"] == "rejected"
        assert reply_metrics(conn, config)["rejected"] == 1
    finally:
        conn.close()

    off = replace(config, first_reply_mode="off")
    conn = connect(config.db_path)
    try:
        result = ingest_and_process(
            conn, off, source="email", payload=load_fixture("email_lead.json")
        )
        assert get_reply(conn, result["leads"][0]) is None
    finally:
        conn.close()


def test_privacy_preview_and_erase(config):
    conn = connect(config.db_path)
    try:
        result = _ingest(conn, config)
        lead_id = result["leads"][0]
        preview = preview_erasure(conn, emails=["rahul.sharma@example.com"])
        assert preview["count"] == 1
        assert preview["leads"] == [lead_id]
        assert preview["first_replies"] == 1

        erased = erase_leads(conn, config, emails=["rahul.sharma@example.com"])
        assert erased["count"] == 1
        assert get_lead(conn, lead_id) is None
        assert get_reply(conn, lead_id) is None
        assert conn.execute("SELECT COUNT(*) AS c FROM events").fetchone()["c"] == 0
        assert not list(config.archive_dir.glob(f"*{lead_id}*"))
        assert not list(config.outbox_dir.glob(f"*{lead_id}*"))
        assert erased["warnings"]
    finally:
        conn.close()


def test_backup_is_consistent_private_and_pruned(config, tmp_path):
    conn = connect(config.db_path)
    try:
        _ingest(conn, config)
    finally:
        conn.close()

    backup_config = replace(config, backup_dir=tmp_path / "backups", backup_retention=2)
    backups = []
    for index in range(3):
        target = backup_config.backup_dir / f"instantlead-2026010{index}-000000.db"
        result = backup_database(backup_config, destination=target)
        assert result["integrity"] == "ok"
        assert result["bytes"] > 0
        backups.append(target)
    remaining = sorted(backup_config.backup_dir.glob("instantlead-*.db"))
    assert len(remaining) == 2
    mode = remaining[0].stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_alerts_fire_and_recover_with_cooldown(config, monkeypatch):
    conn = connect(config.db_path)
    sent = []
    try:
        monkeypatch.setattr(
            alerts,
            "check_healthz",
            lambda cfg: {"ok": False, "status_code": 503, "payload": {}, "error": "down"},
        )
        monkeypatch.setattr(
            alerts,
            "send_alert_message",
            lambda cfg, subject, text: sent.append(subject) or "test",
        )
        alert_config = replace(config, alert_webhook_url="", alert_emails=["ops@example.com"])
        first = alerts.check_and_alert(conn, alert_config)
        assert first["sent"] == 1
        assert sent == ["InstantLead /healthz is failing"]
        second = alerts.check_and_alert(conn, alert_config)
        assert second["sent"] == 0

        monkeypatch.setattr(
            alerts,
            "check_healthz",
            lambda cfg: {"ok": True, "status_code": 200, "payload": {"ok": True}, "error": ""},
        )
        recovered = alerts.check_and_alert(conn, alert_config)
        assert recovered["sent"] == 1
        assert sent[-1] == "InstantLead /healthz recovered"
    finally:
        conn.close()


def test_alert_on_dead_letter_growth(config, monkeypatch):
    conn = connect(config.db_path)
    sent = []
    try:
        create_event(conn, source="form", external_id="dead-1", payload={"id": "dead-1"})
        conn.execute("UPDATE events SET status = 'dead' WHERE external_id = 'dead-1'")
        conn.commit()
        monkeypatch.setattr(
            alerts,
            "check_healthz",
            lambda cfg: {"ok": True, "status_code": 200, "payload": {"ok": True}, "error": ""},
        )
        monkeypatch.setattr(
            alerts,
            "send_alert_message",
            lambda cfg, subject, text: sent.append(subject) or "test",
        )
        result = alerts.check_and_alert(conn, config)
        assert result["dead_letter"]["count"] == 1
        assert any("dead-letter" in subject for subject in sent)
    finally:
        conn.close()


def test_demo_generator_is_labelled_and_unique():
    records = generate_demo_leads(100, 42)
    assert len(records) == 100
    assert {record["expected_category"] for record in records} == {
        "HOT",
        "WARM",
        "COLD",
        "SPAM",
    }
    spam = [record for record in records if record["expected_spam"]]
    assert len(spam) == 5
    assert all(record["expected_tier"] == "COLD" for record in spam)
    external = {json.dumps(record["payload"], sort_keys=True) for record in records}
    assert len(external) == 100


def test_second_client_locale_config(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAND_CONFIG", "config/clients/coastal-realty.yaml")
    monkeypatch.setenv("BUSINESS_TZ", "")
    monkeypatch.setenv("CURRENCY", "")
    monkeypatch.setenv("DIGEST_TIME", "")
    reset_config_cache()
    try:
        cfg = get_config()
        assert cfg.business_tz == "America/New_York"
        assert cfg.currency == "USD"
        assert cfg.digest_time == (18, 0)
    finally:
        monkeypatch.delenv("BRAND_CONFIG", raising=False)
        reset_config_cache()


def test_healthz_reports_first_reply_and_wal(config):
    from fastapi.testclient import TestClient

    from service.main import create_app

    conn = connect(config.db_path)
    try:
        _ingest(conn, config)
    finally:
        conn.close()

    app = create_app(config, start_background=False)
    with TestClient(app) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["wal"] is True
    assert body["pending_replies"] == 1
    assert body["first_reply"]["total"] == 1


def test_init_and_connect_are_idempotent(config):
    init_db(config.db_path)
    init_db(config.db_path)
    conn = connect(config.db_path)
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(leads)")}
        assert {"first_reply_at", "first_reply_seconds", "first_reply_status"} <= columns
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()
