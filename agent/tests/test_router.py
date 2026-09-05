"""Routing. Tier is derived from intent, never decided separately, so the two
can never disagree."""

from __future__ import annotations

import json

import pytest

from agent import config
from agent.llm import ScriptedRouterLLM
from agent.router import route, route_deterministic
from agent.schemas import Confidence, Intent, Tier


class TestTierAssignment:
    @pytest.mark.parametrize(
        "query,tier",
        [
            ("Who is on reserve at BLR on 2026-09-15?", Tier.LOOKUP),
            ("Which flights depart DEL on 2026-09-15?", Tier.LOOKUP),
            ("How many duty hours has C-1042 accrued?", Tier.LOOKUP),
            ("List all certifications expiring within 30 days.", Tier.LOOKUP),
            ("If C-2087 covers P-2291, does any rule breach?", Tier.REPLACEMENT),
            ("C-1042 calls in sick. Which flights are uncrewed?", Tier.REPLACEMENT),
            ("Who can cover P-2291?", Tier.REPLACEMENT),
            ("Produce ranked resolution options with costs.", Tier.CONSEQUENCE),
            ("What if we delay DX412 by 40 minutes instead?", Tier.CONSEQUENCE),
            ("C-5417's recurrent training lapsed. Resolve their 19 Sep duty.", Tier.CONSEQUENCE),
        ],
    )
    def test_tier(self, query, tier):
        assert route(query).tier is tier

    def test_tier_always_matches_intent(self):
        for query in ("who is on reserve", "does any rule breach", "rank the options"):
            r = route(query)
            assert r.tier is r.intent.tier


class TestIntents:
    @pytest.mark.parametrize(
        "query,intent",
        [
            ("Who is on reserve at BLR?", Intent.LOOKUP_RESERVE),
            ("How much headroom does C-1042 have?", Intent.LOOKUP_DUTY_CLOCK),
            ("Which certifications expire next month?", Intent.LOOKUP_CERT),
            ("Which flights depart BLR?", Intent.LOOKUP_FLIGHT),
            ("What does RULE-DUTY-02 mean?", Intent.EXPLAIN_RULE),
            ("Does assigning C-2087 breach anything?", Intent.CHECK_LEGALITY),
            ("Who can cover P-2291?", Intent.FIND_REPLACEMENT),
            ("Which flights are affected by the closure?", Intent.IMPACT_OF_EVENT),
            ("Produce ranked options with costs.", Intent.RANK_OPTIONS),
            ("What if we delay departure instead?", Intent.SIMULATE_WHATIF),
            ("C-5417's licence lapsed — resolve their assignment.", Intent.RESOLVE_ILLEGAL),
        ],
    )
    def test_intent(self, query, intent):
        assert route(query).intent is intent


class TestJointPlanDetection:
    def test_explicit_joint(self):
        q = "Both A320 captains are sick at 00:30Z. Give the optimal joint plan."
        assert route(q).intent is Intent.JOINT_PLAN

    def test_explicit_joint_without_named_crew(self):
        """'both captains are sick' is two events without naming either one."""
        q = "Both captains called in sick. Give the optimal plan."
        assert route(q).intent is Intent.JOINT_PLAN

    def test_ranking_over_two_events_upgrades_to_joint(self):
        """S6's shape with no 'joint' or 'both' wording at all — the upgrade
        has to come from the entities, not the phrasing."""
        q = ("C-3940 is sick on P-2205 and C-1938 is sick on P-2212. "
             "Produce ranked options with costs.")
        r = route(q)
        assert r.intent is Intent.JOINT_PLAN
        assert any("JOINT_PLAN" in n for n in r.notes)

    def test_two_crew_without_disruption_is_not_joint(self):
        """Naming two people is not two disruptions."""
        q = "Can C-1042 cover for C-2087 on P-2291?"
        assert route(q).intent is not Intent.JOINT_PLAN


class TestLLMFallback:
    def test_deterministic_rules_abstain_on_gibberish(self):
        assert route_deterministic("qqq zzz") is None

    def test_llm_consulted_only_when_rules_abstain(self):
        llm = ScriptedRouterLLM(intent="LOOKUP_CREW")
        route("Who is on reserve at BLR?", llm)
        assert llm.calls == [], "deterministic path must not call the model"

    def test_llm_used_when_rules_abstain(self):
        llm = ScriptedRouterLLM(intent="SIMULATE_WHATIF", confidence="medium")
        r = route("qqq zzz", llm)
        assert r.used_llm
        assert r.intent is Intent.SIMULATE_WHATIF
        assert r.confidence is Confidence.MEDIUM

    def test_unparseable_reply_degrades_to_low_confidence_lookup(self):
        """A placeholder client returns prose, not JSON. Degrade to the safest
        intent — a lookup reads data and changes nothing."""
        r = route("qqq zzz")  # default PlaceholderLLM
        assert r.confidence is Confidence.LOW
        assert r.tier is Tier.LOOKUP
        assert r.notes


class TestGoldQuestionCoverage:
    """The router's tier must match dCortex's own label on the gold set.

    This is not the eval harness — it only checks classification, which is the
    part `agent/` owns. Scoring answers is `evals/harness.py` (issue #13).
    """

    @staticmethod
    def _questions():
        path = config.DATA_DIR / "questions.json"
        if not path.exists():
            pytest.skip("dataset not vendored")
        return json.loads(path.read_text())

    def test_tier_matches_dcortex_labels_exactly(self):
        """Currently 38/38. The classifier is deterministic, so any drop is a
        real regression rather than noise — fail on the first one."""
        questions = self._questions()
        misses = [
            f"{q['question_id']}(want T{q['tier']}, got T{int(route(q['prompt']).tier)})"
            for q in questions
            if int(route(q["prompt"]).tier) != q["tier"]
        ]
        assert not misses, f"{len(misses)}/{len(questions)} misrouted: {misses}"

    def test_every_question_routes_without_error(self):
        for q in self._questions():
            assert route(q["prompt"]).intent in Intent


class TestNoModelOnTheGoldSet:
    """The routing claim is "38/38 with no model at all". That only holds if
    every question matches a rule.

    Two originally fell through (Q14 network shape, Q16 risk score). They still
    *scored* correct, because the fallback defaults to LOOKUP_CREW at tier 1
    and both happen to be tier 1 — but that is luck, not classification. Had
    either been tier 2 or 3 the fallback would have been wrong.
    """

    def test_every_gold_question_matches_a_rule(self):
        from agent.entities import extract
        from agent.router import route_deterministic

        fell = [
            q["question_id"]
            for q in self._questions()
            if route_deterministic(q["prompt"], extract(q["prompt"])) is None
        ]
        assert not fell, f"fell through to the model: {fell}"

    def test_routing_never_consults_the_model(self):
        class Tripwire:
            def complete(self, **kw):
                raise AssertionError("the model was consulted")

            def stream(self, **kw):
                raise AssertionError("the model was consulted")

        for q in self._questions():
            assert int(route(q["prompt"], Tripwire()).tier) == q["tier"], q["question_id"]

    @staticmethod
    def _questions():
        import json

        from agent import config

        path = config.DATA_DIR / "questions.json"
        if not path.exists():
            pytest.skip("dataset not vendored")
        return json.loads(path.read_text())


class TestDisruptionVocabulary:
    """A controller stating that someone cannot fly is asking for cover,
    however they phrase it. The gold questions only say "calls in sick", so a
    router tuned on them alone missed almost everything real — "Captain of
    BLR->BOM not available" fell through to a flight timetable.
    """

    @pytest.mark.parametrize(
        "phrasing",
        [
            "Captain of BLR->BOM not available on 2026-09-17",
            "skipper on the BOM run is out",
            "my atr skipper just bailed on tomorrows rotation",
            "C-1042 went sick", "C-1042 is off sick", "C-1042 no-show",
            "C-1042 didn't show", "C-1042 failed to report",
            "C-1042 can't fly tomorrow", "C-1042 unable to operate",
            "C-1042 has been stood down", "C-1042 pulled from P-2291",
            "C-1042 is timed out", "C-1042 maxed out on hours",
            "C-1042 busted his limits", "C-1042 is fatigued",
            "C-1042's licence expired", "C-1042 lost currency",
            "C-1042 is grounded", "P-2291 is uncrewed",
            "we're a man down on P-2291", "P-2291 needs a captain",
            "no captain on DX412", "short a pilot for the morning bank",
            "i need a warm body for the 0600 out of DEL",
            "who else could sit in that left seat",
            "get me a sub for C-1042", "backfill P-2291",
            "who's available to cover DX412",
        ],
    )
    def test_disruption_routes_to_tier_two(self, phrasing):
        from agent.entities import extract

        r = route_deterministic(phrasing, extract(phrasing))
        assert r is not None, "fell through to the model"
        assert r.tier is Tier.REPLACEMENT, f"got {r.intent} via {r.matched_rule}"

    def test_disruption_with_an_impact_question_asks_what_breaks(self):
        from agent.entities import extract

        q = "C-1042 called in sick for P-2291. Which flights are affected?"
        r = route_deterministic(q, extract(q))
        assert r.intent is Intent.IMPACT_OF_EVENT

    def test_two_disruptions_become_a_joint_plan(self):
        from agent.entities import extract

        q = "C-3940 is out on P-2205 and C-1938 is out on P-2212"
        r = route_deterministic(q, extract(q))
        assert r.intent is Intent.JOINT_PLAN

    @pytest.mark.parametrize(
        "listing",
        ["Which certifications expire next month?",
         "List all certifications expiring within 30 days of 2026-09-15.",
         "Which flights depart DEL on 2026-09-15?"],
    )
    def test_listing_queries_are_not_disruptions(self, listing):
        """`expired?` matched the bare "expire" in a listing query and routed
        it as a disruption. Past tense only."""
        from agent.entities import extract

        r = route_deterministic(listing, extract(listing))
        assert r.tier is Tier.LOOKUP, f"got {r.intent} via {r.matched_rule}"


class TestDestinationFilter:
    def test_two_stations_become_origin_and_destination(self):
        from agent.advisor import _flight_filters
        from agent.entities import extract

        got = _flight_filters(extract("Captain of BLR->BOM not available on 2026-09-17"))
        assert got == {"dep_station": "BLR", "arr_station": "BOM", "date": "2026-09-17"}

    def test_one_station_leaves_destination_open(self):
        from agent.advisor import _flight_filters
        from agent.entities import extract

        got = _flight_filters(extract("Which flights depart BLR on 2026-09-17?"))
        assert "arr_station" not in got
