"""The trust gate.

If this passes something it should not, an invented duty hour reaches a
controller. These tests are the closest thing this repo has to a safety case.
"""

from __future__ import annotations

from agent.schemas import TraceEntry
from agent.verifier import build_evidence, extract_claims, verify


def trace(*results):
    return [TraceEntry(tool="lookup", result=r) for r in results]


class TestSupportedClaims:
    def test_identifier_from_tool_result(self):
        t = trace({"crew_id": "C-1042", "name": "A. Nair"})
        assert verify("C-1042 is available.", t).ok

    def test_number_from_tool_result(self):
        t = trace({"cost_inr": 18500})
        assert verify("It costs 18,500.", t).ok

    def test_currency_formatting_normalised(self):
        t = trace({"cost_inr": 41200})
        assert verify("All-in ₹41,200.", t).ok

    def test_float_within_tolerance(self):
        t = trace({"duty_hours_7d": 20.93})
        assert verify("She has 20.93 hours.", t).ok

    def test_number_inside_a_prose_field(self):
        """Rule details carry their numbers in a string, not a field."""
        t = trace({"detail": "would exceed 60h/7d by 1h20m (total 61.33h)"})
        assert verify("Exceeds by 1h20m, reaching 61.33h.", t).ok

    def test_nested_structures_are_walked(self):
        t = trace({"options": [{"crew": {"id": "C-3310"}, "cost_inr": 18500}]})
        assert verify("Use C-3310 at 18,500.", t).ok

    def test_echoing_an_argument_is_allowed(self):
        """An id the model passed in came from the controller or an earlier
        result, so repeating it is not a fabrication."""
        t = [TraceEntry(tool="check_legality", args={"crew_id": "C-2087"}, result={"legal": False})]
        assert verify("C-2087 is not legal.", t).ok


class TestRejectedClaims:
    def test_invented_crew_id(self):
        t = trace({"crew_id": "C-1042"})
        result = verify("C-9999 can cover.", t)
        assert not result.ok
        assert [c.value for c in result.unsupported] == ["C-9999"]

    def test_invented_number(self):
        t = trace({"cost_inr": 18500})
        result = verify("It costs 22,750.", t)
        assert not result.ok
        assert "22,750" in [c.value for c in result.unsupported]

    def test_float_outside_tolerance(self):
        t = trace({"duty_hours_7d": 20.93})
        assert not verify("She has 24.50 hours.", t).ok

    def test_no_tools_means_nothing_is_sourced(self):
        result = verify("C-1042 can cover for 18,500.", [])
        assert not result.ok
        assert any("no tools" in n for n in result.notes)

    def test_partial_support_still_fails(self):
        """One good claim does not carry a bad one."""
        t = trace({"crew_id": "C-1042", "cost_inr": 18500})
        result = verify("C-1042 costs 18,500, and C-9999 costs 24,000.", t)
        assert not result.ok
        assert {c.value for c in result.unsupported} == {"C-9999", "24,000"}


class TestNumericFloor:
    def test_small_integers_are_prose_not_claims(self):
        """'all 7 rules' and 'the 2 options' are narration, not assertions
        about the world, so they need no source."""
        t = trace({"crew_id": "C-1042"})
        assert verify("C-1042 passes all 7 rules across 2 days.", t).ok

    def test_large_numbers_always_need_a_source(self):
        t = trace({"crew_id": "C-1042"})
        assert not verify("C-1042 costs 18,500.", t).ok

    def test_small_float_is_still_a_claim(self):
        """3.0 hours of delay is a real quantity even though it is small."""
        t = trace({"crew_id": "C-1042"})
        assert not verify("C-1042 needs a 3.5 hour delay.", t).ok


class TestEvidenceAndClaims:
    def test_evidence_records_which_tool_supplied_what(self):
        t = [
            TraceEntry(tool="lookup", result={"crew_id": "C-1042"}),
            TraceEntry(tool="find_options", result={"cost_inr": 18500}),
        ]
        ev = build_evidence(t)
        assert ev.has_identifier("C-1042") == "lookup"
        assert ev.has_number(18500) == "find_options"

    def test_claim_carries_its_source(self):
        t = trace({"crew_id": "C-1042"})
        result = verify("C-1042 is free.", t)
        assert result.claims[0].source_tool == "lookup"

    def test_claims_deduplicated(self):
        claims = extract_claims("C-1042 and C-1042 again")
        assert len(claims) == 1

    def test_tool_errors_surface_as_notes(self):
        t = [TraceEntry(tool="check_legality", error="INTERNAL: not implemented")]
        result = verify("Nothing to report.", t)
        assert any("check_legality" in n for n in result.notes)

    def test_summary_names_the_bad_claims(self):
        t = trace({"crew_id": "C-1042"})
        assert "C-9999" in verify("Use C-9999.", t).summary()
