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
