from __future__ import annotations

import pytest

from tests.conftest import load_fixture
from tools.lib.llm import validate_extraction
from tools.lib.normalize import extract_leads
from tools.lib.scoring import score_lead


def _score(source: str, fixture: str, config, llm=None) -> dict:
    lead = extract_leads(source, load_fixture(fixture), "2026-10-23T09:00:00+00:00")[0]
    lead["lead_id"] = "TESTLEAD0001"
    return score_lead(lead, config, llm)


def test_form_lead_scores_hot(config):
    scored = _score("form", "form_lead.json", config)
    assert scored["tier"] == "HOT"
    assert scored["score"] >= 70
    assert scored["is_spam"] is False
    assert sum(row["points"] for row in scored["score_breakdown"]) == scored["score"] or scored["score"] in {0, 100}


def test_google_form_is_warm(config):
    scored = _score("google_form", "google_form_lead.json", config)
    assert scored["tier"] == "WARM"
    assert 40 <= scored["score"] < 70


def test_whatsapp_scores_hot_with_free_text_facts(config):
    scored = _score("whatsapp", "whatsapp_lead.json", config)
    assert scored["tier"] == "HOT"
    assert scored["budget_max"] == 15_000_000
    assert scored["timeline_days"] == 7


def test_instagram_is_warm_without_budget(config):
    scored = _score("instagram", "instagram_lead.json", config)
    assert scored["tier"] == "WARM"
    assert scored["budget_min"] is None


def test_spam_is_quarantined(config):
    scored = _score("form", "spam_form.json", config)
    assert scored["is_spam"] is True
    assert scored["tier"] == "COLD"


def test_llm_intent_can_raise_by_ten_only(config):
    base = _score("google_form", "google_form_lead.json", config)
    boosted = _score("google_form", "google_form_lead.json", config, {"intent": "high"})
    assert boosted["score"] == base["score"] + 10
    assert any("AI-assisted" in row["evidence"] for row in boosted["score_breakdown"])


def test_validate_extraction_drops_ungrounded_values():
    message = "Need a 3BHK in Powai. Budget 1.2-1.5 Cr, ready to visit this week."
    data = {
        "intent": "high",
        "budget_min": 12000000,
        "budget_max": 15000000,
        "timeline_days": 7,
        "property_type": "3BHK",
        "location": "Powai",
        "preferred_language": "Klingon",
    }
    result = validate_extraction(data, message)
    assert result["intent"] == "high"
    assert result["budget_min"] == 12_000_000
    assert result["property_type"] == "3BHK"
    assert result["location"] == "Powai"
    assert "preferred_language" not in result

    ungrounded = validate_extraction(
        {"property_type": "Penthouse", "location": "Dubai", "intent": "bogus"},
        message,
    )
    assert "property_type" not in ungrounded
    assert "location" not in ungrounded
    assert ungrounded["intent"] == "none"


def test_llm_budget_is_not_used_when_rules_already_found_it(config):
    lead = extract_leads("form", load_fixture("form_lead.json"))[0]
    scored = score_lead(lead, config, {"budget_min": 1, "budget_max": 2})
    assert scored["budget_min"] == 12_000_000
    assert scored["budget_max"] == 15_000_000


def test_repeat_enquiry_adds_points(config):
    lead = extract_leads("form", load_fixture("form_lead.json"))[0]
    lead["touch_count"] = 2
    scored = score_lead(lead, config)
    assert any("Repeat enquiry" in reason for reason in scored["score_reasons"])
