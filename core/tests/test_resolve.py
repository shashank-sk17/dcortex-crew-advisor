"""Entity resolution: suggest, never substitute.

`C-1042` and `C-1024` differ by one transposed digit. In this dataset one is a
captain and the other is nobody. Auto-correcting would silently dispatch a
different human being to an aircraft, so a near match must always come back as
a question for the controller.
"""

from __future__ import annotations

import pytest

from core.resolve import resolve

CREW = {
    "C-1042": "Captain, BLR",
    "C-1021": "Cabin Crew, BLR",
    "C-4999": "Cabin Crew, BLR",
    "C-3310": "Captain, BLR",
}
LABEL = lambda record: record   # resolve passes the record, not the key


class TestExisting:
    def test_a_real_id_resolves(self):
        r = resolve("crew", "C-1042", CREW, LABEL)
        assert r.exists and not r.needs_confirmation


class TestTypos:
    def test_transposition_is_offered_as_a_question(self):
        r = resolve("crew", "C-1024", CREW, LABEL)
        assert not r.exists
        assert r.needs_confirmation
        assert r.likely[0].value == "C-1042"
        assert "Did you mean" in r.message()

    def test_it_never_answers_on_the_suggestion(self):
        """The suggestion is a question. Nothing here returns the near match
        as though it were the requested id."""
        r = resolve("crew", "C-1024", CREW, LABEL)
        assert r.query == "C-1024"
        assert "will not guess" in r.message()

    def test_the_label_lets_a_controller_confirm(self):
        """"C-1042" alone is not checkable; "C-1042 (Captain, BLR)" is."""
        assert "Captain, BLR" in resolve("crew", "C-1024", CREW, LABEL).message()


class TestNonexistent:
    def test_a_made_up_id_is_not_dressed_up_as_a_typo(self):
        """C-9999 vs C-4999 scores 0.833 on difflib — identical to the real
        transposition above. String distance cannot separate them, so this
        reports what it found instead of implying a correction."""
        r = resolve("crew", "C-9999", CREW, LABEL)
        assert not r.exists
        assert not r.needs_confirmation
        assert "There is no crew C-9999" in r.message()
        assert "Did you mean" not in r.message()

    def test_something_far_off_says_so_and_sizes_the_space(self):
        r = resolve("crew", "C-0000", CREW, LABEL)
        assert not r.needs_confirmation
        msg = r.message()
        assert "nothing close" in msg and "4 crews" in msg

    def test_it_never_returns_empty_silently(self):
        """Every outcome carries a message. Nothing fails quietly."""
        for query in ("C-1042", "C-1024", "C-9999", "C-0000", "banana"):
            assert resolve("crew", query, CREW, LABEL).message().strip()


@pytest.fixture(scope="module")
def port():
    from agent.tools_postgres import load_database_url

    if load_database_url() is None:
        pytest.skip("no DATABASE_URL")
    from core.port import CoreToolPort

    return CoreToolPort()


class TestThroughTheToolBoundary:
    """The same behaviour where a controller actually meets it."""

    def test_transposed_crew_id_asks(self, port):
        from agent.tools import dispatch

        e = dispatch(port, "check_legality",
                     {"crew_id": "C-1024", "pairing_id": "P-2291"})
        assert e.error.startswith("NEEDS_CONFIRMATION")
        assert "C-1042" in e.error

    def test_transposed_pairing_id_asks(self, port):
        from agent.tools import dispatch

        e = dispatch(port, "find_options", {"pairing_id": "P-2921", "role": "Captain"})
        assert "P-2291" in e.error

    def test_made_up_ids_are_refused_not_guessed(self, port):
        from agent.tools import dispatch

        for args in ({"pairing_id": "P-9999", "role": "Captain"},
                     {"flight_id": "DX999-2026-09-15", "role": "Captain"}):
            e = dispatch(port, "find_options", args)
            assert e.error.startswith("UNRESOLVED_ENTITY")
            assert "Did you mean" not in e.error

    def test_a_real_id_still_works(self, port):
        from agent.tools import dispatch

        e = dispatch(port, "find_options", {"pairing_id": "P-2291", "role": "Captain"})
        assert e.error is None and e.result["options"]
