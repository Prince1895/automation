from __future__ import annotations

import pytest

from tests.conftest import load_fixture
from tools.lib.normalize import extract_leads, meta_event_slices


def _one(source: str, fixture: str) -> dict:
    return extract_leads(source, load_fixture(fixture), "2026-10-23T09:00:00+00:00")[0]


def test_website_form_is_normalized():
    lead = _one("form", "form_lead.json")
    assert lead["name"] == "Rahul Sharma"
    assert lead["phone_e164"] == "+919876543210"
    assert lead["email"] == "rahul.sharma@example.com"
    assert lead["property_type"] == "3BHK"
    assert lead["location"] == "Powai, Mumbai"
    assert (lead["budget_min"], lead["budget_max"]) == (12_000_000, 15_000_000)
    assert lead["timeline_days"] == 30
    assert lead["consent"] is True


def test_google_form_question_titles_are_mapped():
    lead = _one("google_form", "google_form_lead.json")
    assert lead["name"] == "Anita Rao"
    assert lead["phone_e164"] == "+919123456789"
    assert lead["email"] == "anita.rao@example.com"
    assert lead["property_type"] == "2BHK"
    assert lead["location"] == "Whitefield, Bengaluru"
    assert lead["timeline_days"] == 90
    assert lead["budget_min"] is None


def test_whatsapp_free_text_is_grounded():
    lead = _one("whatsapp", "whatsapp_lead.json")
    assert lead["name"] == "Rahul Sharma"
    assert lead["phone_e164"] == "+919876543210"
    assert lead["email"] == "rahul.sharma@example.com"
    assert lead["property_type"] == "3BHK"
    assert lead["location"] == "Powai"
    assert (lead["budget_min"], lead["budget_max"]) == (12_000_000, 15_000_000)
    assert lead["timeline_days"] == 7


def test_instagram_message_extracts_phone_and_requirement():
    lead = _one("instagram", "instagram_lead.json")
    assert lead["name"] is None
    assert lead["email"] is None
    assert lead["phone_e164"] == "+919988776655"
    assert lead["property_type"] == "3BHK"
    assert lead["location"] == "Bandra"
    assert lead["budget_min"] is None


def test_email_enquiry_is_normalized():
    lead = _one("email", "email_lead.json")
    assert lead["name"] == "Vikram Mehta"
    assert lead["email"] == "vikram.mehta@example.com"
    assert lead["phone_e164"] == "+919012345678"
    assert lead["property_type"] == "4BHK"
    assert lead["location"] in {"Kondapur", "Hyderabad"}
    assert (lead["budget_min"], lead["budget_max"]) == (30_000_000, 35_000_000)
    assert lead["timeline_days"] == 30
    assert lead["message"].startswith("Subject: Enquiry")


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError):
        extract_leads("carrier_pigeon", {})


def test_meta_slices_split_each_message_and_ignore_status_events():
    whatsapp = load_fixture("whatsapp_lead.json")
    events = meta_event_slices(whatsapp)
    assert len(events) == 1
    assert events[0][0] == "whatsapp"
    assert events[0][1] == "wamid.TEST-3001"

    instagram = meta_event_slices(load_fixture("instagram_lead.json"))
    assert instagram[0][0] == "instagram"
    assert instagram[0][1] == "mid.TEST-4001"

    status_only = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"statuses": [{}]}}]}]}
    assert meta_event_slices(status_only) == []
