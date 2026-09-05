from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.pii import Address, PIISafeModel, redact_pii_text

client = TestClient(app)


# ---------------------------------------------------------------- PII regex regression

@pytest.mark.parametrize(
    "text",
    ["2026-09-15", "DX412-2026-09-15", "2026-09-14T18:00:00Z", "C-1042", "P-2291",
     "RULE-DUTY-02", "VT-DXA", "DX401"],
)
def test_pii_redaction_never_touches_dates_or_ids(text):
    assert redact_pii_text(text) == text


def test_pii_redaction_still_catches_email_and_phone():
    assert redact_pii_text("contact a@b.com") == "contact [REDACTED_EMAIL]"
    assert "[REDACTED_PHONE]" in redact_pii_text("call +91 98765 43210")
    assert "[REDACTED_PHONE]" in redact_pii_text("call 9876543210")


@pytest.mark.parametrize(
    "text,label",
    [
        ("Aadhaar: 1234 5678 9012", "AADHAAR"),
        ("PAN ABCDE1234F on file", "PAN"),
        ("Passport A1234567", "PASSPORT"),
        ("Card 4111 1111 1111 1111", "CARD"),
        ("server at 192.168.1.1", "IP"),
    ],
)
def test_pii_redaction_catches_indian_id_and_financial_patterns(text, label):
    assert f"[REDACTED_{label}]" in redact_pii_text(text)


def test_card_redaction_requires_valid_luhn_not_just_digit_count():
    """A 16-digit sequence that fails Luhn must not be redacted as a card --
    and, more subtly, its first 12 digits must not then get mis-matched as
    an Aadhaar number either (found via testing: the Aadhaar pattern needs
    an explicit guard against being part of a longer 4-group sequence)."""
    text = "bad card 1234 5678 9012 3456"
    assert redact_pii_text(text) == text


def test_sensitive_field_names_redacted_even_when_nested():
    """Structural regression: field-name-based redaction (address, DOB,
    health, financial, government-ID fields with no reliable content
    pattern) must apply inside nested objects, not just top-level fields --
    the original implementation only checked the outer model's own fields."""

    class Nested(PIISafeModel):
        date: str
        home_address: str
        medical_notes: str

    class Outer(PIISafeModel):
        crew_id: str
        contacts: list[Nested]

    dumped = Outer(
        crew_id="C-1042",
        contacts=[Nested(date="2026-09-15", home_address="221B Baker Street, BLR",
                          medical_notes="no restrictions")],
    ).model_dump()
    assert dumped["crew_id"] == "C-1042"
    nested = dumped["contacts"][0]
    assert nested["date"] == "2026-09-15"  # not sensitive, must survive
    assert nested["home_address"] == "[REDACTED_ADDRESS]"
    assert nested["medical_notes"] == "[REDACTED_ADDRESS]"


def test_address_marker_type_redacted_regardless_of_field_name():
    class M(PIISafeModel):
        crew_id: str
        pickup_location: Address

    dumped = M(crew_id="C-1042", pickup_location="12 MG Road, BLR").model_dump()
    assert dumped["pickup_location"] == "[REDACTED_ADDRESS]"


def test_optional_and_list_address_fields_also_redacted():
    """A plain `annotation is Address` identity check misses Optional[Address]
    and list[Address] -- typing wraps Address inside a Union/generic-alias
    that is never `is Address` itself. Found via testing: both leaked
    completely unredacted before this was fixed."""

    class M(PIISafeModel):
        crew_id: str
        backup_address: Address | None = None
        prior_addresses: list[Address] = []

    dumped = M(
        crew_id="C-1042",
        backup_address="9 Residency Rd, BLR",
        prior_addresses=["1 MG Rd", "2 Brigade Rd"],
    ).model_dump()
    assert dumped["backup_address"] == "[REDACTED_ADDRESS]"
    assert dumped["prior_addresses"] == ["[REDACTED_ADDRESS]", "[REDACTED_ADDRESS]"]


# ---------------------------------------------------------------- endpoint smoke tests, real DB

def test_crew_list_and_detail():
    r = client.get("/api/v1/crew", params={"rank": "Captain", "base": "BLR"})
    assert r.status_code == 200
    assert r.json()["meta"]["count"] > 0

    r = client.get("/api/v1/crew/C-1042")
    assert r.status_code == 200
    assert r.json()["data"]["name"] == "A. Nair"

    r = client.get("/api/v1/crew/C-9999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CREW_NOT_FOUND"


def test_duty_clock_q02_canary():
    """The project's own canary value -- if this is wrong, the window math
    feeding this endpoint is wrong everywhere."""
    r = client.get("/api/v1/crew/C-1042/duty-clock")
    assert r.status_code == 200
    assert r.json()["data"]["duty_hours_7d"] == 20.93


def test_certifications_no_date_corruption():
    r = client.get("/api/v1/crew/C-1042/certifications")
    assert r.status_code == 200
    for cert in r.json()["data"]:
        assert "REDACTED" not in cert["valid_from"]
        assert "REDACTED" not in cert["valid_to"]


def test_flight_and_pairing_ids_not_redacted():
    r = client.get("/api/v1/flights/DX412-2026-09-15")
    assert r.status_code == 200
    assert r.json()["data"]["flight_id"] == "DX412-2026-09-15"

    r = client.get("/api/v1/pairings/P-2291")
    assert r.status_code == 200
    assert r.json()["data"]["days"][0]["flights"][0]["flight_id"] == "DX412-2026-09-15"


def test_rules_endpoint_hides_embeddings():
    r = client.get("/api/v1/rules", params={"rule_id": "RULE-DUTY-02"})
    assert r.status_code == 200
    rule = r.json()["data"][0]
    assert set(rule.keys()) == {"rule_id", "text", "params"}  # no embedding/search_tsv leak


# ---------------------------------------------------------------- RULE-CERT-06 regression (Trap 3)

def test_cert06_is_one_sided_not_a_range_check():
    """C-3310 is the S2 answer key's #1 pick (legal reserve, ₹18,500). A
    two-sided valid_from<=date<=valid_to check makes this fail for every
    crew member, because `licence.valid_from` is always future-dated -- see
    docs/RULES.md Trap 3. This must come back eligible."""
    r = client.get("/api/v1/crew/C-3310/legality", params={"pairing_id": "P-2291", "date": "2026-09-15"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["checks"]["certification_valid"] is True
    assert data["eligible"] is True


def test_c2087_correctly_ineligible_for_a_real_reason():
    """Answer key cites RULE-DUTY-02 for C-2087; this API's simplified
    duty_limits_ok (current hours, not prospective) won't catch that specific
    breach, but C-2087 independently has only 4h rest before this pairing's
    06:00Z report (needs 12h) -- so the verdict is still correctly False."""
    r = client.get("/api/v1/crew/C-2087/legality", params={"pairing_id": "P-2291", "date": "2026-09-15"})
    assert r.status_code == 200
    assert r.json()["data"]["eligible"] is False


# ---------------------------------------------------------------- /advisory regression

def test_advisory_matches_s2_answer_key_top_pick():
    payload = {
        "request_id": "ADV-TEST-001",
        "scenario": {"type": "CREW_REPLACEMENT", "date": "2026-09-15", "pairing_id": "P-2291"},
        "affected_crew": {"crew_id": "C-1042"},
        "constraints": {"required_rank": "Captain"},
        "options": {"include_reserve": True, "max_candidates": 5},
    }
    r = client.post("/api/v1/advisory", json=payload)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["advisory"]["recommended_crew"]["crew_id"] == "C-3310"
    top = data["candidates"][0]
    assert top["crew_id"] == "C-3310"
    assert top["estimated_cost"]["amount"] == 18500


def test_advisory_never_recommends_the_affected_crew_member():
    payload = {
        "request_id": "ADV-TEST-003",
        "scenario": {"type": "CREW_REPLACEMENT", "date": "2026-09-15", "pairing_id": "P-2291"},
        "affected_crew": {"crew_id": "C-1042"},
        "options": {"include_reserve": True, "max_candidates": 20},
    }
    r = client.post("/api/v1/advisory", json=payload)
    assert r.status_code == 200
    ids = [c["crew_id"] for c in r.json()["data"]["candidates"]]
    assert "C-1042" not in ids


def test_advisory_rejects_unsupported_scenario_type():
    payload = {"request_id": "ADV-TEST-004", "scenario": {"type": "STATION_CLOSURE", "date": "2026-09-17"}}
    r = client.post("/api/v1/advisory", json=payload)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_REQUEST"
