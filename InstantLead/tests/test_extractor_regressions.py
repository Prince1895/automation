import pytest
from tools.lib.llm import extract
from tools.lib.scoring import score_lead
from tools.lib.config import get_config

@pytest.fixture
def cfg():
    return get_config()

def test_location_hallucination(cfg):
    # "interested in learning more" should NOT trigger a location
    msg = "Hi, I am interested in learning more about your properties."
    extracted = extract(msg, cfg)
    assert extracted.get("location") is None or extracted.get("location") == ""

def test_timeline_hallucination(cfg):
    # Message with no timing words but containing digits (like phone) should have NULL timeline
    msg = "Please call me at +91 9876543210. I want to know the price."
    extracted = extract(msg, cfg)
    assert extracted.get("timeline_days") is None

def test_intent_classification(cfg):
    # "send me info and pricing" should be MEDIUM, not HIGH
    msg = "Hi, please send me info and pricing for your 3BHKs."
    # We simulate the LLM extraction here as well as the keyword scoring
    lead = {"message": msg, "phone_e164": "+919876543210", "email": "test@example.com"}
    scored = score_lead(lead, cfg, llm={}) # Rules-only scoring
    
    # Based on the new HIGH_INTENT list, "info" and "pricing" are MEDIUM
    # Score should be significantly lower than 65
    assert scored["score"] < 60
    assert scored["tier"] != "HOT"

def test_seller_intent(cfg):
    # "looking to list" should not be high buying intent
    msg = "I am looking to list my property for sale."
    lead = {"message": msg, "phone_e164": "+919876543210", "email": "test@example.com"}
    scored = score_lead(lead, cfg, llm={})
    assert scored["tier"] in ["WARM", "COLD"]
