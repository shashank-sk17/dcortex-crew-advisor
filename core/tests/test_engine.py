"""The engine, scored against dCortex's own answer keys.

Correctness here is proved rather than asserted: every option, cost and delay
is compared to the published key. These need the database, so they skip
without DATABASE_URL rather than failing.
"""

from __future__ import annotations

import json

import pytest

from agent import config

pytestmark = pytest.mark.skipif(
    __import__("agent.tools_postgres", fromlist=["load_database_url"]).load_database_url()
    is None,
    reason="no DATABASE_URL",
)


@pytest.fixture(scope="module")
def port():
    from core.port import CoreToolPort

    return CoreToolPort()


@pytest.fixture(scope="module")
def scenarios():
    path = config.DATA_DIR / "scenarios.json"
    if not path.exists():
        pytest.skip("dataset not vendored")
    return {s["scenario_id"]: s for s in json.loads(path.read_text())}


def assert_options_match(got, want):
    assert len(got) == len(want), f"{len(got)} options, key has {len(want)}"
    for g, w in zip(got, want):
        assert g["crew_id"] == w["crew_id"], f"rank {w['rank']}"
        assert g["cost_inr"] == w["cost_inr"], f"{w['crew_id']}"
        assert g["delay_hours"] == w["delay_hours"], f"{w['crew_id']}"


class TestAgainstAnswerKeys:
    def test_s1_atr_captain(self, port, scenarios):
        s = scenarios["S1"]
        got = port.find_options(role="Captain", pairing_id=s["event"]["pairing_id"])
        assert_options_match(got["options"], s["answer_key"]["options"])

    def test_s2_flagship_two_day_pairing(self, port, scenarios):
        got = port.find_options(role="Captain", pairing_id="P-2291")
        assert_options_match(got["options"], scenarios["S2"]["answer_key"]["options"])

    def test_s6_both_aircraft(self, port, scenarios):
        ak = scenarios["S6"]["answer_key"]
        assert_options_match(
            port.find_options(role="Captain", pairing_id="P-2205")["options"],
            ak["options_dxa"])
        assert_options_match(
            port.find_options(role="Captain", pairing_id="P-2212")["options"],
            ak["options_dxb"])


class TestRipple:
    def test_day_one_and_the_orphaned_day_two(self, port, scenarios):
        """Crew fly pairings, not legs. P-2291 overnights at DEL, so losing
        its captain on day 1 puts day 2 at risk too."""
        ak = scenarios["S2"]["answer_key"]
        r = port.ripple(scenarios["S2"]["event"])
        assert r["uncovered_flights"] == ak["uncovered_flights_day1"]
        assert r["at_risk_flights"] == ak["uncovered_flights_day2"]
        assert r["passengers"] == ak["passengers_at_risk_day1"]


class TestJointPlan:
    def test_optimal_total(self, port, scenarios):
        jp = port.joint_plan([{"pairing_id": "P-2205", "role": "Captain"},
                              {"pairing_id": "P-2212", "role": "Captain"}])
        assert jp["total_cost_inr"] == \
            scenarios["S6"]["answer_key"]["optimal_joint_plan"]["total_cost_inr"]

    def test_disjointness_enforced(self, port):
        """The trap: solve each aircraft alone and both take the cheapest
        reserve, producing an infeasible plan."""
        jp = port.joint_plan([{"pairing_id": "P-2205", "role": "Captain"},
                              {"pairing_id": "P-2212", "role": "Captain"}])
        assert jp["assign_P-2205"]["crew_id"] != jp["assign_P-2212"]["crew_id"]

    def test_ties_are_counted_not_hidden(self, port):
        """Twenty assignments cost the same; dCortex calls them equally
        correct, so the UI must not present one as uniquely right."""
        jp = port.joint_plan([{"pairing_id": "P-2205", "role": "Captain"},
                              {"pairing_id": "P-2212", "role": "Captain"}])
        assert jp["equal_cost_alternatives"] == 20


class TestKnownTraps:
    def test_c3305_legal_day_one_breaches_day_two(self, port):
        """The dataset's teaching case. Day 2 must be checked against a window
        that already contains day 1, or a two-day cover looks legal twice."""
        got = port.find_options(role="Captain", pairing_id="P-2291")
        assert "C-3305" not in {o["crew_id"] for o in got["options"]}

    def test_reserve_outside_its_window_is_excluded_not_repriced(self, port):
        """C-3310's window is 06:00-18:00; P-2205 reports 01:30. Someone on
        reserve duty is not on a day off, so day-off pricing would invent an
        option the desk does not have."""
        got = port.find_options(role="Captain", pairing_id="P-2205")
        assert "C-3310" not in {o["crew_id"] for o in got["options"]}

    def test_certifications_are_checked_on_expiry_only(self, port):
        """All 150 licence rows carry a future valid_from, and C-2087's runs
        2028-11-06 to 2026-09-18 — a start after its own end. Enforcing
        valid_from excludes every pilot in the airline."""
        got = port.find_options(role="Captain", pairing_id="P-2291")
        assert got["options"], "no captain is legal — valid_from is being enforced"

    def test_base_applies_to_the_first_day_only(self, port):
        """P-2291 overnights at DEL. Checking base on every day rejects every
        BLR crew for not being based where the pairing slept."""
        got = port.find_options(role="Captain", pairing_id="P-2291")
        assert "C-3310" in {o["crew_id"] for o in got["options"]}
