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


class TestDatesAndTimes:
    """A date is one claim, not three numbers.

    Splitting 2026-09-15 into 2026/09/15 floods the ledger and, worse, would
    let a wrong date pass on the strength of a matching year.
    """

    def test_date_verified_whole(self):
        t = trace({"date": "2026-09-15"})
        result = verify("Rostered on 2026-09-15.", t)
        assert result.ok
        assert [c.value for c in result.claims] == ["2026-09-15"]

    def test_wrong_date_rejected(self):
        t = trace({"date": "2026-09-15"})
        assert not verify("Rostered on 2026-09-17.", t).ok

    def test_year_alone_does_not_support_a_date(self):
        t = trace({"note": "season 2026"})
        assert not verify("Rostered on 2026-09-15.", t).ok

    def test_date_components_do_not_pollute_the_number_index(self):
        """Without stripping, '2026-09-15' would supply 2026 as evidence."""
        t = trace({"date": "2026-09-15"})
        assert not verify("The duty ran 2026 hours.", t).ok

    def test_times_verified_whole(self):
        t = trace({"window": "06:00-18:00"})
        assert verify("On call 06:00 to 18:00.", t).ok


class TestDerivedCounts:
    def test_result_cardinality_is_evidence(self):
        """"12 records" is derived from what a tool returned, not invented."""
        t = trace([{"crew_id": f"C-{i:04d}"} for i in range(12)])
        assert verify("12 records.", t).ok

    def test_a_wrong_count_is_still_rejected(self):
        t = trace([{"crew_id": f"C-{i:04d}"} for i in range(12)])
        assert not verify("47 records.", t).ok


class TestSummaryWording:
    def test_untraced_claims_named(self):
        assert "C-9999" in verify("Use C-9999.", trace({"crew_id": "C-1042"})).summary()

    def test_no_tools_reads_as_no_source_not_as_zero_claims(self):
        r = verify("Nothing to report.", [])
        assert not r.ok
        assert "no tool ran" in r.summary()

    def test_sourced_but_silent_answer(self):
        r = verify("Nothing to report.", trace({"crew_id": "C-1042"}))
        assert r.ok and "nothing asserted" in r.summary()


class TestPostgresScalarTypes:
    """Postgres returns types Python's numeric tower does not cover.

    Every one of these produced a false UNVERIFIED before it was handled.
    """

    def test_decimal_counts_as_a_number(self):
        from decimal import Decimal

        t = trace({"block_hours": Decimal("2.75"), "cost_inr": Decimal("18500")})
        assert verify("Block time 2.75 hours at 18,500.", t).ok

    def test_wrong_value_still_rejected_against_a_decimal(self):
        from decimal import Decimal

        assert not verify("Block time 9.99 hours.", trace({"block_hours": Decimal("2.75")})).ok

    def test_datetime_matches_its_rendered_form(self):
        import datetime as dt

        t = trace({"last_rest_ended": dt.datetime(2026, 9, 13, 2, 0, tzinfo=dt.timezone.utc)})
        assert verify("Rest ended 2026-09-13 at 02:00.", t).ok

    def test_date_and_time_objects_indexed(self):
        import datetime as dt

        t = trace({"date": dt.date(2026, 9, 15), "start": dt.time(6, 0)})
        assert verify("On 2026-09-15 from 06:00.", t).ok


class TestErrorTextIsEvidence:
    def test_id_named_in_a_tool_error_is_sourced(self):
        """Explaining why a tool failed means repeating what it said. "no
        fixture covers P-2218" makes P-2218 sourced, not invented."""
        t = [TraceEntry(tool="find_options",
                        error="UNRESOLVED_ENTITY: no fixture covers P-2218")]
        assert verify("Cannot answer: no fixture covers P-2218.", t).ok

    def test_an_id_that_appears_nowhere_still_fails(self):
        t = [TraceEntry(tool="find_options",
                        error="UNRESOLVED_ENTITY: no fixture covers P-2218")]
        assert not verify("Cannot answer: no fixture covers P-9999.", t).ok


class TestDerivedNumbers:
    """A number computed from evidence is not a fabrication.

    Claude drafted "₹5,500 more than the recommended option" — 24,000 − 18,500,
    both verified. Rejecting it discarded a correct, useful answer. A false
    positive costs as much as a false negative: it throws away good work and
    teaches people to ignore the gate.

    The earlier instinct was to precompute that one delta in the engine. That
    is a workaround — it fixes the instance and leaves the defect, so the next
    derived figure fails identically.
    """

    def _options(self):
        return [TraceEntry(tool="find_options",
                           result={"options": [{"cost_inr": 18500},
                                               {"cost_inr": 24000}]})]

    def test_difference_is_accepted_and_labelled(self):
        r = verify("That is 5,500 more than the recommended option.", self._options())
        assert r.ok
        claim = next(c for c in r.claims if c.value == "5,500")
        assert claim.status == "derived"
        assert "24000 - 18500" in claim.derivation

    def test_sum_is_accepted(self):
        assert verify("Together they come to 42,500.", self._options()).ok

    def test_a_number_that_derives_from_nothing_still_fails(self):
        r = verify("It costs 7,300 more.", self._options())
        assert not r.ok
        assert r.unsupported[0].value == "7,300"

    def test_directly_returned_values_are_sourced_not_derived(self):
        r = verify("The reserve callout is 18,500.", self._options())
        assert next(c for c in r.claims if c.value == "18,500").status == "sourced"

    def test_derivation_needs_both_operands_in_evidence(self):
        """One evidence number plus an invented one must not derive."""
        t = [TraceEntry(tool="lookup", result={"cost_inr": 18500})]
        assert not verify("That is 5,500 more.", t).ok

    def test_summary_reports_how_many_were_derived(self):
        r = verify("That is 5,500 more.", self._options())
        assert "derived" in r.summary()

    def test_small_numbers_are_not_derived_into_existence(self):
        """The claim floor still applies — prose integers are not claims, and
        must not become a back door for arbitrary arithmetic."""
        from agent.verifier import build_evidence

        assert build_evidence(self._options()).derive(5.0) is None
