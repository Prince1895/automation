from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from service.main import create_app
from tests.conftest import load_fixture


def _client(config) -> TestClient:
    return TestClient(create_app(config, start_background=False))


def test_health_and_root(config):
    with _client(config) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        body = health.json()
        assert body["ok"] is True
        assert body["dry_run"] is True
        assert client.get("/").json()["service"] == "InstantLead"


def test_form_webhook_requires_token_and_is_idempotent(config):
    payload = load_fixture("form_lead.json")
    with _client(config) as client:
        assert client.post("/webhooks/form", json=payload).status_code == 401
        first = client.post(
            "/webhooks/form",
            json=payload,
            headers={"X-Webhook-Token": "test-form-secret"},
        )
        assert first.status_code == 200
        assert first.json() == {"ok": True, "queued": 1}
        second = client.post(
            "/webhooks/form",
            json=payload,
            headers={"X-Webhook-Token": "test-form-secret"},
        )
        assert second.json() == {"ok": True, "queued": 0}


def test_form_webhook_accepts_hmac_signature(config):
    payload = load_fixture("form_lead.json")
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"test-form-secret", raw, hashlib.sha256).hexdigest()
    with _client(config) as client:
        response = client.post(
            "/webhooks/form",
            content=raw,
            headers={"Content-Type": "application/json", "X-Signature-256": signature},
        )
        assert response.status_code == 200
        assert response.json()["queued"] == 1


def test_meta_verification_challenge(config):
    with _client(config) as client:
        ok = client.get(
            "/webhooks/meta",
            params={"hub.mode": "subscribe", "hub.verify_token": "test-verify-token", "hub.challenge": "12345"},
        )
        assert ok.status_code == 200
        assert ok.text == "12345"
        bad = client.get(
            "/webhooks/meta",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
        )
        assert bad.status_code == 403


def test_meta_webhook_verifies_signature_and_queues_message(config):
    payload = load_fixture("whatsapp_lead.json")
    raw = json.dumps(payload).encode()
    with _client(config) as client:
        assert client.post("/webhooks/meta", content=raw).status_code == 403
        signature = "sha256=" + hmac.new(b"test-meta-secret", raw, hashlib.sha256).hexdigest()
        response = client.post(
            "/webhooks/meta",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "queued": 1}


def test_status_only_meta_webhook_queues_nothing(config):
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"test-meta-secret", raw, hashlib.sha256).hexdigest()
    with _client(config) as client:
        response = client.post(
            "/webhooks/meta",
            content=raw,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": signature},
        )
        assert response.json() == {"ok": True, "queued": 0}
