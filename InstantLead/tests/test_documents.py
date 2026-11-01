from __future__ import annotations

from tests.conftest import load_fixture
from tools.lib.email_render import email_word_count, lead_subject, render_lead_email
from tools.lib.facts import build_lead_facts, with_valid_logo
from tools.lib.normalize import extract_leads
from tools.lib.pdf import render_lead_pdf
from tools.lib.scoring import score_lead


def _facts(config, fixture: str = "form_lead.json", source: str = "form") -> dict:
    lead = extract_leads(source, load_fixture(fixture))[0]
    lead["lead_id"] = "TESTLEAD0001"
    scored = score_lead(lead, config)
    scored["status"] = "New"
    return with_valid_logo(build_lead_facts(scored, config), config)


def test_email_subject_contains_tier_and_facts(config):
    facts = _facts(config)
    subject = lead_subject(facts)
    assert subject.startswith("[HOT]")
    assert "Rahul Sharma" in subject
    assert "3BHK" in subject
    assert "₹1.2 Cr" in subject


def test_email_is_compact_and_factual(config):
    facts = _facts(config)
    _, html, text = render_lead_email(facts)
    assert email_word_count(html) <= 160
    assert "Rahul Sharma" in html
    assert "Score" not in html or "HOT" in html
    assert "Not provided" not in html or "Email" in html
    assert "Lead TESTLEAD0001" in html
    assert "PDF" in html
    assert len(text.split()) <= 160


def test_missing_values_render_as_not_provided(config):
    lead = extract_leads("instagram", load_fixture("instagram_lead.json"))[0]
    lead["lead_id"] = "TESTLEAD0002"
    scored = score_lead(lead, config)
    facts = with_valid_logo(build_lead_facts(scored, config), config)
    assert facts["name"] == "Not provided"
    assert facts["email"] == "Not provided"
    assert facts["budget"] == "Not provided"
    subject, html, _ = render_lead_email(facts)
    assert "Not provided" in html
    assert "Dubai" not in subject


def test_pdf_is_branded_and_small(config):
    facts = _facts(config)
    path = render_lead_pdf(facts, config)
    assert path.exists()
    assert path.stat().st_size > 10_000
    assert path.stat().st_size < 500_000
    assert path.read_bytes().startswith(b"%PDF")
