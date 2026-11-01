from __future__ import annotations

from tools.lib.util import (
    extract_location,
    extract_phone,
    extract_property_type,
    flatten_mapping,
    format_budget,
    normalize_email,
    normalize_phone,
    parse_budget,
    parse_budget_from_text,
    parse_timeline,
)


def test_phone_normalization():
    assert normalize_phone("98765 43210") == ("+91 98765 43210", "+919876543210")
    assert normalize_phone("+91 98765 43210")[1] == "+919876543210"
    assert normalize_phone("09876543210")[1] == "+919876543210"
    assert normalize_phone("not a phone") == (None, None)
    assert extract_phone("Call +91 90123 45678 today") == "+919012345678"


def test_email_normalization():
    assert normalize_email("Rahul.Sharma@Example.com") == "rahul.sharma@example.com"
    assert normalize_email("no email here") is None


def test_budget_parsing():
    assert parse_budget("1.2-1.5 Cr")[:2] == (12_000_000, 15_000_000)
    assert parse_budget("50L-75L")[:2] == (5_000_000, 7_500_000)
    assert parse_budget("1200000")[:2] == (1_200_000, 1_200_000)
    assert format_budget(12_000_000, 15_000_000) == "₹1.2 Cr–₹1.5 Cr"
    assert format_budget(None, None) == "Not provided"
    assert parse_budget("$1.2M-1.5M")[:2] == (1_200_000, 1_500_000)
    assert parse_budget("USD 1.2 million")[:2] == (1_200_000, 1_200_000)
    assert format_budget(1_200_000, 1_500_000, "USD") == "$1.2M–$1.5M"


def test_budget_from_text_does_not_mistake_phone_or_bhk_for_budget():
    assert parse_budget_from_text("Budget is $1.2M")[:3] == (1_200_000, 1_200_000, "USD")
    assert parse_budget_from_text("Call me on 9876543210")[:2] == (None, None)
    assert parse_budget_from_text("Need a 3BHK in Powai")[:2] == (None, None)
    assert parse_budget_from_text("Budget 1.2-1.5 Cr, call 9876543210")[:2] == (
        12_000_000,
        15_000_000,
    )


def test_timeline_parsing():
    assert parse_timeline("Within 30 days")[1] == 30
    assert parse_timeline("2-3 months")[1] == 90
    assert parse_timeline("this week")[1] == 7
    assert parse_timeline("this month")[1] == 30
    assert parse_timeline("just exploring") == ("Not provided", None)


def test_property_and_location_extraction():
    text = "Need a 3 bhk in Powai, budget 1.2 Cr"
    assert extract_property_type(text) == "3BHK"
    assert extract_location(text) == "Powai"
    assert extract_location("interested in buying a villa") is None


def test_flatten_mapping_snake_cases_question_titles():
    flat = flatten_mapping({"Full name": "Anita", "Contact number": "9999999999"})
    assert flat == {"full_name": "Anita", "contact_number": "9999999999"}
