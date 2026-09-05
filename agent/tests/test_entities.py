"""Entity extraction must be exact — resolving the wrong captain is the worst
failure this system can have, so nothing here is allowed to be approximate."""

from __future__ import annotations

import json

import pytest

from agent import config
from agent.entities import extract, mask


class TestIdentifiers:
    def test_crew_pairing_and_date(self):
        e = extract("Can C-1042 cover P-2291 on 15 Sep out of BLR?")
        assert e.crew_ids == ["C-1042"]
        assert e.pairing_ids == ["P-2291"]
        assert e.dates == ["2026-09-15"]
        assert e.stations == ["BLR"]

    def test_similar_ids_stay_distinct(self):
        """C-1042 and C-1024 must never be conflated — the whole reason we
        pattern-match identifiers instead of embedding them."""
        e = extract("Compare C-1042 with C-1024")
        assert e.crew_ids == ["C-1042", "C-1024"]

    def test_flight_id_not_double_counted_as_flight_no(self):
        e = extract("Is DX412-2026-09-15 crewed?")
        assert e.flight_ids == ["DX412-2026-09-15"]
        assert e.flight_nos == []

    def test_bare_flight_number(self):
        e = extract("What time does DX412 depart?")
        assert e.flight_nos == ["DX412"]
        assert e.flight_ids == []

    def test_rules_and_aircraft(self):
        e = extract("Does VT-DXA breach RULE-DUTY-02 or RULE-FDP-01?")
        assert e.aircraft == ["VT-DXA"]
        assert e.rule_ids == ["RULE-DUTY-02", "RULE-FDP-01"]

    def test_dedupe_preserves_first_mention(self):
        e = extract("C-1042 ... C-2087 ... C-1042 again")
        assert e.crew_ids == ["C-1042", "C-2087"]


class TestStations:
    def test_only_real_stations(self):
        e = extract("Flights from BLR to DEL, not XYZ or ABC")
        assert e.stations == ["BLR", "DEL"]

    def test_false_friends_rejected(self):
        """Three-letter uppercase words that are not stations."""
        e = extract("The FDP limit in UTC terms")
        assert e.stations == []


class TestDates:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("on 2026-09-15", "2026-09-15"),
            ("on 15 Sep", "2026-09-15"),
            ("on 15 September 2026", "2026-09-15"),
            ("on Sep 15", "2026-09-15"),
            ("on the 15th", "2026-09-15"),
            ("15th Sep", "2026-09-15"),
        ],
    )
    def test_formats(self, text, expected):
        assert extract(text).dates == [expected]

    def test_bare_day_outside_the_week_is_ignored(self):
        """'the 3rd' is not in the dataset week, so it is not a date."""
        assert extract("the 3rd option").dates == []

    def test_invalid_date_dropped(self):
        assert extract("on 2026-02-30").dates == []

    def test_times(self):
        e = extract("BLR closed 08:00-14:00Z, sick call at 05:00Z")
        assert e.times == ["08:00", "14:00", "05:00"]

    def test_invalid_time_dropped(self):
        assert extract("at 99:99") .times == []


class TestRoles:
    @pytest.mark.parametrize(
        "text,role",
        [
            ("the captain called in", "Captain"),
            ("CPT C-1042", "Captain"),
            ("first officer needed", "First Officer"),
            ("FO on the roster", "First Officer"),
            ("senior cabin crew", "Senior Cabin Crew"),
        ],
    )
    def test_role_synonyms(self, text, role):
        assert role in extract(text).roles

    def test_senior_cabin_crew_beats_cabin_crew(self):
        """Longest-match ordering: 'senior cabin crew' must not be read as
        plain 'cabin crew' plus noise."""
        roles = extract("senior cabin crew").roles
        assert roles[0] == "Senior Cabin Crew"


class TestMasking:
    def test_ids_become_type_tokens(self):
        got = mask("Captain C-1042 calls in sick at 05:00Z on 15 Sep for P-2291")
        assert got == "Captain <CREW> calls in sick at <TIME> on <DATE> for <PAIRING>"

    def test_different_crew_collapse_to_one_template(self):
        """The point of masking: two questions of the same shape become
        identical, so the router classifies shape rather than identity."""
        a = mask("Captain C-1042 calls in sick for P-2291")
        b = mask("Captain C-3231 calls in sick for P-2224")
        assert a == b

    def test_stations_masked_but_words_untouched(self):
        got = mask("Flights from BLR to DEL")
        assert "<STATION>" in got
        assert got.count("<STATION>") == 2
        assert mask("The FDP limit") == "The FDP limit"


class TestVocabularyMatchesDataset:
    """config.py hardcodes vocabulary for speed; these assert it is still true."""

    @staticmethod
    def _load(name):
        path = config.DATA_DIR / f"{name}.json"
        if not path.exists():
            pytest.skip("dataset not vendored")
        return json.loads(path.read_text())

    def test_stations(self):
        flights = self._load("flights")
        actual = {f["dep_station"] for f in flights} | {f["arr_station"] for f in flights}
        assert actual == set(config.STATIONS)

    def test_aircraft_and_types(self):
        flights = self._load("flights")
        assert {f["aircraft"] for f in flights} == set(config.AIRCRAFT)
        assert {f["aircraft_type"] for f in flights} == set(config.AIRCRAFT_TYPES)

    def test_roles(self):
        crew = self._load("crew")
        assert {c["rank"] for c in crew} == set(config.ROLES)

    def test_rule_ids(self):
        rules = self._load("rules")["rules"]
        assert tuple(r["rule_id"] for r in rules) == config.ALL_RULE_IDS

    def test_cert_types(self):
        certs = self._load("certifications")
        assert {c["cert_type"] for c in certs} == set(config.CERT_TYPES)


class TestHorizon:
    """"Within 30 days" is a number the answer depends on, so it is read from
    the question rather than assumed."""

    @pytest.mark.parametrize("text, days", [
        ("List all certifications expiring within 30 days of 2026-09-15.", 30),
        ("List crew whose licence expires in the next 30 days.", 30),
        ("anything lapsing in 2 weeks?", 14),
        ("certs expiring within a month", None),      # no number, no guess
        ("who is on reserve at BLR on 15 Sep?", None),
    ])
    def test_reads_the_stated_window(self, text, days):
        assert extract(text).horizon_days == days

    def test_a_bare_day_is_not_mistaken_for_a_horizon(self):
        """"the 15th" resolves as a date; it must not also become 15 days."""
        e = extract("who is on reserve on the 15th?")
        assert e.dates == ["2026-09-15"] and e.horizon_days is None
