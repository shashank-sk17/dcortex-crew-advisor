"""End-to-end loop, plus the exemplar corpus and tool boundary.

Everything runs on the placeholder client — no key, no network, no SDK.
"""

from __future__ import annotations

import pytest

from agent.advisor import Advisor, build_answer, seed_calls, tools_for
from agent.exemplars import ExemplarIndex, exemplar_block, load_exemplars
from agent.llm import PlaceholderLLM
from agent.prompts import system_prompt
from agent.router import route
from agent.schemas import Confidence, ConsequenceAnswer, Intent, LookupAnswer, Tier
from agent.tools import TOOL_NAMES, PlaceholderToolPort, ToolPort, dispatch


class TestToolPort:
    def test_placeholder_satisfies_the_protocol(self):
        assert isinstance(PlaceholderToolPort(), ToolPort)

    def test_lookup_reads_real_data(self):
        rows = PlaceholderToolPort().lookup("crew", {"base": "BLR", "rank": "Captain"})
        assert rows and all(r["rank"] == "Captain" for r in rows)

    def test_explain_rule_returns_params(self):
        rule = PlaceholderToolPort().explain_rule("RULE-DUTY-02")
        assert rule["params"]["max_duty_hours"] == 60

    def test_unimplemented_tools_refuse_rather_than_invent(self):
        """The whole architecture exists to prevent a plausible fabrication
        here. Not-yet-built must surface as an error, never as a number."""
        entry = dispatch(PlaceholderToolPort(), "check_legality",
                         {"crew_id": "C-1042", "pairing_id": "P-2291"})
        assert entry.error and entry.result is None

    def test_unknown_tool_is_traced_not_raised(self):
        entry = dispatch(PlaceholderToolPort(), "nonexistent", {})
        assert "unknown tool" in entry.error

    def test_bad_arguments_are_traced_not_raised(self):
        entry = dispatch(PlaceholderToolPort(), "lookup", {"wrong": 1})
        assert entry.error


class TestPlanning:
    def test_toolset_narrowed_by_intent(self):
        names = {t["name"] for t in tools_for(Intent.LOOKUP_RESERVE)}
        assert names == {"lookup"}
        assert "joint_plan" not in names

    def test_unknown_intent_gets_everything(self):
        assert len(tools_for(Intent.LOOKUP_ROSTER)) >= 1

    @pytest.mark.parametrize(
        "query,tool",
        [
            ("What does RULE-DUTY-02 say?", "explain_rule"),
            ("How many duty hours has C-1042 accrued?", "duty_clock"),
            ("Who is on reserve at BLR?", "lookup"),
            ("If C-2087 covers P-2291, any breach?", "check_legality"),
            ("Who can cover P-2291?", "find_options"),
        ],
    )
    def test_seed_calls_from_entities(self, query, tool):
        calls = seed_calls(route(query))
        assert calls and calls[0].name == tool

    def test_seed_passes_extracted_arguments_through(self):
        call = seed_calls(route("How many duty hours has C-1042 accrued on 15 Sep?"))[0]
        assert call.args["crew_id"] == "C-1042"
        assert call.args["date"] == "2026-09-15"

    def test_no_seed_without_the_needed_entities(self):
        assert seed_calls(route("Who can cover?")) == []


class TestAdvisor:
    def test_tier_one_answers_from_real_data(self):
        r = Advisor().ask("Who is on reserve at BLR?")
        assert r.tier is Tier.LOOKUP
        assert isinstance(r.answer, LookupAnswer)
        assert r.answer.count > 0
        assert r.narrative

    def test_explain_rule_end_to_end(self):
        r = Advisor().ask("What does RULE-DUTY-02 say?")
        assert r.intent is Intent.EXPLAIN_RULE
        assert r.trace[0].tool == "explain_rule"
        assert any(c.id == "RULE-DUTY-02" for c in r.citations)

    def test_failed_tool_lowers_confidence(self):
        """core/ is not built, so tier 2 cannot be answered yet — and the
        advisor must say so rather than producing something plausible."""
        r = Advisor().ask("If C-2087 covers P-2291, does any rule breach?")
        assert r.confidence is Confidence.LOW
        assert r.unknowns

    def test_narrative_never_contains_unsourced_claims(self):
        for query in (
            "Who is on reserve at BLR?",
            "What does RULE-FDP-01 say?",
            "Which flights depart DEL on 2026-09-15?",
        ):
            r = Advisor().ask(query)
            from agent.verifier import verify

            assert verify(r.narrative, r.trace).ok, query

    def test_loop_terminates(self):
        advisor = Advisor(llm=PlaceholderLLM())
        r = advisor.ask("Who is on reserve at BLR?")
        assert len(r.trace) < 20

    def test_response_serialises(self):
        d = Advisor().ask("Who is on reserve at BLR?").to_dict()
        assert d["tier"] == 1 and isinstance(d["intent"], str)

    def test_stream_emits_contract_events(self):
        events = list(Advisor().stream("What does RULE-REST-04 say?"))
        kinds = {e.event for e in events}
        assert {"tool_call", "tool_result", "token", "done"} <= kinds
        assert events[-1].event == "done"


class TestAnswerAssembly:
    def test_tier_three_body(self):
        r = route("Produce ranked options with costs for P-2291.")
        assert isinstance(build_answer(r, []), ConsequenceAnswer)

    def test_empty_trace_is_survivable(self):
        r = route("Who is on reserve at BLR?")
        assert build_answer(r, []).rows == []


class TestExemplars:
    def test_all_38_loaded_and_masked(self):
        rows = load_exemplars()
        if not rows:
            pytest.skip("dataset not vendored")
        assert len(rows) == 38
        assert all(e.masked for e in rows)
        assert {e.tier for e in rows} == {1, 2, 3}

    def test_block_is_small_enough_to_inline(self):
        """The reason there is no retrieval on the routing path: the whole
        corpus fits in the cached prompt (DECISIONS.md #15)."""
        block = exemplar_block()
        if not block:
            pytest.skip("dataset not vendored")
        assert len(block) // 4 < 2000

    def test_advisor_prompt_omits_exemplars_by_default(self):
        """836 of 2,250 input tokens per call were exemplars the advisor never
        reads — the router classifies 38/38 without a model at all."""
        prompt = system_prompt(Intent.FIND_REPLACEMENT)
        assert "Worked examples" not in prompt
        assert "This request" in prompt

    def test_exemplars_available_when_asked_for(self):
        """The router's fallback path is the one caller that wants them."""
        assert "Worked examples" in system_prompt(Intent.FIND_REPLACEMENT,
                                                  with_exemplars=True)

    def test_index_returns_contrast_across_tiers(self):
        index = ExemplarIndex()
        if not index.exemplars:
            pytest.skip("dataset not vendored")
        matches = index.search("who is on reserve at BLR", min_similarity=0.0)
        assert len({m.exemplar.tier for m in matches}) == len(matches)

    def test_index_abstains_below_threshold(self):
        """A misleading exemplar is worse than none."""
        index = ExemplarIndex()
        if not index.exemplars:
            pytest.skip("dataset not vendored")
        assert index.search("zzz qqq", min_similarity=0.99) == []


class TestToolSchemas:
    def test_names_unique_and_registered(self):
        from agent.tools import TOOL_SCHEMAS

        names = [t["name"] for t in TOOL_SCHEMAS]
        assert len(names) == len(set(names)) == len(TOOL_NAMES)

    def test_every_schema_is_well_formed(self):
        from agent.tools import TOOL_SCHEMAS

        for tool in TOOL_SCHEMAS:
            assert tool["description"].strip()
            schema = tool["input_schema"]
            assert schema["type"] == "object"
            for required in schema.get("required", []):
                assert required in schema["properties"], tool["name"]

    def test_port_implements_every_tool(self):
        port = PlaceholderToolPort()
        for name in TOOL_NAMES:
            assert callable(getattr(port, name, None)), name


class TestToolLoopDeduplication:
    """Small local models re-request identical calls until the cap.

    Observed with llama3.1:8b: nine identical duty_clock calls for one
    question. Results are deterministic, so a repeat buys nothing.
    """

    def test_identical_calls_run_once(self):
        from agent.llm import LLMResponse, PlaceholderLLM, ToolCall

        same = ToolCall(id="x", name="explain_rule", args={"rule_id": "RULE-DUTY-02"})
        llm = PlaceholderLLM([
            LLMResponse(tool_calls=[same], stop_reason="tool_use"),
            LLMResponse(tool_calls=[same], stop_reason="tool_use"),
            LLMResponse(text="done"),
        ])
        r = Advisor(llm=llm).ask("What does RULE-DUTY-02 say?")
        assert [e.tool for e in r.trace] == ["explain_rule"]

    def test_loop_stops_when_every_call_is_a_repeat(self):
        from agent.llm import LLMResponse, PlaceholderLLM, ToolCall

        same = ToolCall(id="x", name="explain_rule", args={"rule_id": "RULE-FDP-01"})
        llm = PlaceholderLLM([LLMResponse(tool_calls=[same], stop_reason="tool_use")] * 20)
        Advisor(llm=llm).ask("What does RULE-FDP-01 say?")
        assert len(llm.calls) < 5, "should break out, not burn the iteration cap"


class TestLookupIsNeverPolished:
    def test_lookup_uses_the_template_verbatim(self):
        """llama3.1:8b answered "what does RULE-DUTY-02 say?" with an invented
        situation — a crew that had exceeded its limits. Nothing existed to
        exceed anything. The verifier passed it because the fabrication was
        narrative, not numeric."""
        from agent import explainer
        from agent.llm import LLMResponse, PlaceholderLLM
        from agent.schemas import AdvisorResponse, Intent, LookupAnswer, Tier

        liar = PlaceholderLLM([LLMResponse(text="The crew has exceeded its duty limits.")])
        resp = AdvisorResponse(tier=Tier.LOOKUP, intent=Intent.EXPLAIN_RULE,
                               answer=LookupAnswer(rows=[{"rule_id": "RULE-DUTY-02"}]))
        assert explainer.polish(resp, liar) == explainer.render(resp)
        assert llm_unused(liar)


def llm_unused(llm) -> bool:
    return not llm.calls


class TestUnavailableCapability:
    """A missing tool must never read as a finding about the operation."""

    def _resp(self, body):
        from agent.schemas import AdvisorResponse, Intent, Tier, TraceEntry
        return AdvisorResponse(
            tier=Tier.REPLACEMENT, intent=Intent.IMPACT_OF_EVENT, answer=body,
            trace=[TraceEntry(tool="ripple", error="INTERNAL: ripple: needs the rules engine in core/")],
        )

    def test_empty_replacement_names_the_gap(self):
        from agent import explainer
        from agent.schemas import ReplacementAnswer

        out = explainer.render(self._resp(ReplacementAnswer()))
        assert "Cannot answer this yet" in out
        assert "ripple" in out
        assert "No legal option found" not in out, "asserts a fact never checked"

    def test_empty_consequence_is_never_blank(self):
        from agent import explainer
        from agent.schemas import ConsequenceAnswer

        assert explainer.render(self._resp(ConsequenceAnswer())).strip()

    def test_no_legal_option_only_after_a_real_search(self):
        from agent import explainer
        from agent.schemas import AdvisorResponse, FunnelStage, Intent, ReplacementAnswer, Tier

        searched = AdvisorResponse(
            tier=Tier.REPLACEMENT, intent=Intent.FIND_REPLACEMENT,
            answer=ReplacementAnswer(funnel=[FunnelStage(stage="legal", count=0, dropped=12,
                                                         reason="rule breach")]),
        )
        assert "No legal option found" in explainer.render(searched)


class TestConfidenceOrdering:
    def test_verifier_rejection_never_raises_confidence(self):
        """A failed tool means LOW. A rejected draft is also bad news, so it
        must not promote the answer to MEDIUM on its way past."""
        from agent.llm import LLMResponse, PlaceholderLLM

        liar = PlaceholderLLM([LLMResponse(text="Use C-9999 for 47,000.")] * 4)
        r = Advisor(llm=liar).ask("If C-2087 covers P-2291, does any rule breach?")
        assert r.confidence is Confidence.LOW


class TestFilterGuardRails:
    """Measured on qwen3:8b: 12 of 16 tier-1 questions failed on an invented
    column name. The guesses were semantically right under another name, so
    the fix is to advertise the real names and alias the near-misses."""

    def test_schema_advertises_real_field_names(self):
        from agent.tools import schemas_for_port

        lookup = [t for t in schemas_for_port(PlaceholderToolPort())
                  if t["name"] == "lookup"][0]
        desc = lookup["input_schema"]["properties"]["filters"]["description"]
        assert "dep_station" in desc and "valid_to" in desc

    def test_schema_falls_back_when_port_cannot_describe_itself(self):
        from agent.tools import TOOL_SCHEMAS, schemas_for_port

        assert schemas_for_port(object()) is TOOL_SCHEMAS

    @pytest.mark.parametrize(
        "guess,real",
        [("departure", "dep_station"), ("origin", "dep_station"),
         ("destination", "arr_station"), ("crew", "crew_id"),
         ("expiry_date", "valid_to"), ("flight", "flight_no"),
         ("pairing", "pairing_id")],
    )
    def test_near_miss_aliased_to_the_real_field(self, guess, real):
        from agent.tools import resolve_filters

        assert resolve_filters("flights", {guess: "X"}, {real}) == {real: "X"}

    def test_alias_is_case_and_space_tolerant(self):
        from agent.tools import resolve_filters

        assert resolve_filters("flights", {"Departure Station": "DEL"},
                               {"dep_station"}) == {"dep_station": "DEL"}

    def test_unknown_field_rejected_naming_the_valid_ones(self):
        from agent.tools import ToolError, resolve_filters

        with pytest.raises(ToolError) as exc:
            resolve_filters("flights", {"wingspan": 30}, {"dep_station", "date"})
        assert "dep_station" in str(exc.value) and "date" in str(exc.value)

    def test_alias_only_applies_when_the_target_exists(self):
        """`crew` must not become `crew_id` on a table without that column."""
        from agent.tools import ToolError, resolve_filters

        with pytest.raises(ToolError):
            resolve_filters("costs", {"crew": "C-1042"}, {"currency"})

    def test_aliases_work_end_to_end_through_the_port(self):
        rows = PlaceholderToolPort().lookup("flights", {"departure": "DEL"})
        assert rows and all(r["dep_station"] == "DEL" for r in rows)


class TestRendererNeverComputes:
    """The 'LLM never calculates' rule binds the renderer too.

    A 21-row lookup printed "… and 11 more". 11 appears in no tool output, so
    the verifier rejected the whole answer — correctly.
    """

    def _long(self):
        from agent import explainer
        from agent.schemas import AdvisorResponse, Intent, LookupAnswer, Tier, TraceEntry

        rows = [{"crew_id": f"C-{1000+i}"} for i in range(explainer.ROW_LIMIT + 11)]
        return AdvisorResponse(
            tier=Tier.LOOKUP, intent=Intent.LOOKUP_CREW, answer=LookupAnswer(rows=rows),
            trace=[TraceEntry(tool="lookup", result=rows)],
        )

    def test_truncation_states_no_derived_number(self):
        from agent import explainer

        out = explainer.render(self._long())
        assert "11 more" not in out
        assert "(list truncated)" in out

    def test_truncated_listing_verifies(self):
        from agent import explainer
        from agent.verifier import verify

        r = self._long()
        assert verify(explainer.render(r), r.trace).ok

    def test_total_is_still_reported(self):
        from agent import explainer

        assert f"{explainer.ROW_LIMIT + 11} records" in explainer.render(self._long())


class TestArrayAndAliasCoverage:
    def test_role_aliases_to_rank(self):
        from agent.tools import resolve_filters

        assert resolve_filters("crew", {"role": "Captain"}, {"rank"}) == {"rank": "Captain"}


class TestLookupDeduplication:
    """A seeded call and the model's own near-identical one return the same
    rows. Concatenating them doubles the count, and the doubled figure matches
    no tool output — so the verifier rejects an otherwise correct answer."""

    def _trace(self):
        from agent.schemas import TraceEntry

        rows = [{"crew_id": "C-3305"}, {"crew_id": "C-3310"}]
        return [TraceEntry(tool="lookup", result=rows),
                TraceEntry(tool="lookup", result=list(rows))]

    def test_duplicate_rows_collapse(self):
        answer = build_answer(route("Who is on reserve at BLR?"), self._trace())
        assert answer.count == 2

    def test_deduplicated_count_verifies(self):
        from agent import explainer
        from agent.schemas import AdvisorResponse, Intent, Tier
        from agent.verifier import verify

        trace = self._trace()
        r = AdvisorResponse(tier=Tier.LOOKUP, intent=Intent.LOOKUP_RESERVE,
                            answer=build_answer(route("Who is on reserve at BLR?"), trace),
                            trace=trace)
        assert verify(explainer.render(r), r.trace).ok

    def test_distinct_rows_are_kept(self):
        from agent.schemas import TraceEntry

        trace = [TraceEntry(tool="lookup", result=[{"crew_id": "C-1"}]),
                 TraceEntry(tool="lookup", result=[{"crew_id": "C-2"}])]
        assert build_answer(route("Who is on reserve at BLR?"), trace).count == 2


class TestValueFormatting:
    """Postgres objects must render as a controller would read them.

    repr of a list of dates is `[datetime.date(2026, 9, 14), ...]` — unreadable,
    and the verifier lifts 2026/14/15 out of it as unsourced numeric claims.
    """

    def test_dates_render_iso(self):
        import datetime as dt
        from agent.explainer import fmt_value

        assert fmt_value(dt.date(2026, 9, 15)) == "2026-09-15"
        assert fmt_value(dt.time(6, 0)) == "06:00:00"

    def test_date_lists_render_without_repr(self):
        import datetime as dt
        from agent.explainer import fmt_value

        out = fmt_value([dt.date(2026, 9, 14), dt.date(2026, 9, 15)])
        assert out == "2026-09-14, 2026-09-15"
        assert "datetime.date" not in out

    def test_decimal_renders_plainly(self):
        from decimal import Decimal
        from agent.explainer import fmt_value

        assert fmt_value(Decimal("2.75")) == "2.75"

    def test_row_with_a_date_array_verifies(self):
        import datetime as dt
        from agent import explainer
        from agent.schemas import AdvisorResponse, Intent, LookupAnswer, Tier, TraceEntry
        from agent.verifier import verify

        rows = [{"crew_id": "C-3305",
                 "dates": [dt.date(2026, 9, 14), dt.date(2026, 9, 15)]}]
        r = AdvisorResponse(tier=Tier.LOOKUP, intent=Intent.LOOKUP_RESERVE,
                            answer=LookupAnswer(rows=rows),
                            trace=[TraceEntry(tool="lookup", result=rows)])
        assert verify(explainer.render(r), r.trace).ok


class TestRecommendationLeads:
    """A ranked table makes the controller do the deciding, which is the work
    the advisor was meant to save. Recommendation first, evidence last."""

    def _answer(self):
        from agent.schemas import FunnelStage, Option, ReplacementAnswer

        cheap = Option(action="Assign Captain C-3310 (reserve callout)",
                       crew_id="C-3310", legal=True, cost_inr=18500, rank=1,
                       rules_checked=["R"] * 7)
        return ReplacementAnswer(
            recommended=cheap, cancellation_multiple=81,
            options=[cheap,
                     Option(action="Assign Captain C-1526 (day-off)", crew_id="C-1526",
                            legal=True, cost_inr=24000, rank=2),
                     Option(action="Cancel all 6 flights", crew_id=None,
                            legal=True, cost_inr=1500000, rank=3)],
            funnel=[FunnelStage("considered", 27),
                    FunnelStage("qualified", 16, 11, "no rating"),
                    FunnelStage("legal", 5)],
        )

    def test_opens_with_the_recommendation(self):
        from agent import explainer

        first = explainer.render_replacement(self._answer()).splitlines()[0]
        assert "C-3310" in first and "18,500" in first

    def test_cancel_is_a_contrast_not_a_ranked_row(self):
        from agent import explainer

        out = explainer.render_replacement(self._answer())
        assert "Against cancelling" in out
        assert "81×" in out
        assert "#3 Cancel" not in out, "cancel listed as a peer option"

    def test_funnel_comes_last_as_evidence(self):
        from agent import explainer

        out = explainer.render_replacement(self._answer())
        assert out.index("C-3310") < out.index("Considered 27")

    def test_ties_are_declared(self):
        from agent import explainer

        a = self._answer()
        a.equal_cost_alternatives = 3
        assert "not a uniquely correct choice" in explainer.render_replacement(a)


class TestCrewNamedWithoutAPairing:
    """"C-1042 is sick" names a person, not a trip.

    It routed correctly and then did nothing: seeding needed a pairing, and
    the model was not going to guess one. The roster knows both the pairing
    and the role, so neither should be guessed by anyone.
    """

    def test_a_bare_crew_id_seeds_a_search(self):
        calls = seed_calls(route("C-1042 is sick"))
        assert calls, "named a crew member and seeded nothing"
        assert calls[0].name == "find_options"
        assert calls[0].args == {"crew_id": "C-1042"}

    def test_it_also_asks_what_breaks(self):
        names = {c.name for c in seed_calls(route("C-1042 is sick"))}
        assert "ripple" in names

    def test_role_comes_from_the_roster_not_a_default(self):
        """Replacing a captain with a first officer is not cover."""
        from agent.tools_fixtures import FixtureToolPort

        port = FixtureToolPort()
        assert port.assignment_for_crew("C-1042") == ("P-2291", "Captain")

    def test_unrostered_crew_refuses_rather_than_defaulting(self):
        from agent.tools import ToolError
        from agent.tools_fixtures import FixtureToolPort

        with pytest.raises(ToolError):
            FixtureToolPort().assignment_for_crew("C-9999")

    def test_a_named_pairing_still_wins(self):
        call = seed_calls(route("Who can cover P-2291 as Captain?"))[0]
        assert call.args["pairing_id"] == "P-2291"


class TestRejectedDraftMessage:
    def test_no_unsupported_claims_gives_a_useful_reason(self):
        """"The model's draft claimed , which no tool output supports" is
        worse than useless — the draft failed because no tool ran."""
        from agent.llm import LLMResponse, PlaceholderLLM

        llm = PlaceholderLLM([LLMResponse(text="Something unsourced.")] * 4)
        r = Advisor(llm=llm).ask("Who can cover P-9999?")
        assert all("claimed ," not in n for n in r.unknowns)


class TestToolErrorsAreNotParaphrased:
    """A tool failure is already written for a controller. Rewriting it can
    only lose or distort the actionable part.

    Asked about C-1045, the model reported "C-1045 isn't rostered on any
    pairing this week" — the tool had said no such crew exists. It also
    claimed ripple needed a crew_id that had been supplied, and dropped the
    "did you mean C-1042" suggestion entirely.

    The verifier passed all of it. The invention was narrative, so it carried
    no number or identifier to check — the same blind spot as the fabricated
    duty-limit warning and the leaked chain of thought.
    """

    def _unavailable(self):
        from agent.schemas import AdvisorResponse, Intent, ReplacementAnswer, Tier, TraceEntry

        return AdvisorResponse(
            tier=Tier.REPLACEMENT, intent=Intent.FIND_REPLACEMENT,
            answer=ReplacementAnswer(),
            trace=[TraceEntry(tool="find_options",
                              error="UNRESOLVED_ENTITY: There is no crew C-1045. "
                                    "Nearest existing: C-1042 (Captain, BLR)")],
        )

    def test_an_empty_answer_is_never_sent_to_the_model(self):
        from agent import explainer
        from agent.llm import LLMResponse, PlaceholderLLM

        liar = PlaceholderLLM([LLMResponse(text="C-1045 is not rostered this week.")])
        out = explainer.polish(self._unavailable(), liar)
        assert "not rostered" not in out
        assert liar.calls == [], "the model was consulted about a tool failure"

    def test_the_suggestion_survives_verbatim(self):
        from agent import explainer

        out = explainer.render(self._unavailable())
        assert "C-1042" in out and "There is no crew C-1045" in out

    def test_a_query_error_is_not_framed_as_a_missing_capability(self):
        """"There is no crew C-1045" is a finding about the question, not a
        gap in what we can do."""
        from agent import explainer

        out = explainer.render(self._unavailable())
        assert "missing capability" not in out
        assert "tools it needs are unavailable" not in out

    def test_a_genuine_capability_gap_still_says_so(self):
        from agent import explainer
        from agent.schemas import AdvisorResponse, ConsequenceAnswer, Intent, Tier, TraceEntry

        r = AdvisorResponse(
            tier=Tier.CONSEQUENCE, intent=Intent.JOINT_PLAN,
            answer=ConsequenceAnswer(),
            trace=[TraceEntry(tool="joint_plan",
                              error="INTERNAL: joint_plan: needs the rules engine")],
        )
        assert "missing capability" in explainer.render(r)

    def test_a_real_answer_is_still_polished(self):
        from agent import explainer
        from agent.llm import LLMResponse, PlaceholderLLM
        from agent.schemas import (AdvisorResponse, Intent, Option,
                                   ReplacementAnswer, Tier, TraceEntry)

        good = AdvisorResponse(
            tier=Tier.REPLACEMENT, intent=Intent.FIND_REPLACEMENT,
            answer=ReplacementAnswer(options=[Option("Assign C-3310", "C-3310", True)]),
            trace=[TraceEntry(tool="find_options", result={"crew_id": "C-3310"})],
        )
        llm = PlaceholderLLM([LLMResponse(text="Use C-3310.")])
        assert explainer.polish(good, llm) == "Use C-3310."


class TestVerdictStatusSurvivesTheToolBoundary:
    """The most dangerous bug found in this system so far.

    `RuleVerdict.failed` compared `status is Verdict.FAIL`. Verdicts cross the
    tool boundary as JSON, so status arrives as the string "FAIL" — identity
    is False, the breach reads as a pass, and an illegal assignment is
    reported legal. Comparison is by value now, and the enum is rebuilt on the
    way in.
    """

    def test_a_string_status_still_counts_as_failed(self):
        from agent.schemas import RuleVerdict

        v = RuleVerdict(rule_id="RULE-DUTY-02", status="FAIL", detail="over by 1h20m")
        assert v.failed, "a breach read as a pass"

    def test_coercion_rebuilds_the_enum(self):
        from agent.advisor import _coerce
        from agent.schemas import RuleVerdict, Verdict

        got = _coerce(RuleVerdict, [{"rule_id": "RULE-FDP-01", "status": "PASS"}])
        assert got[0].status is Verdict.PASS

    def test_a_breach_is_never_narrated_as_legal(self):
        from agent import explainer
        from agent.schemas import (AdvisorResponse, Intent, ReplacementAnswer,
                                   RuleVerdict, Tier, TraceEntry)

        r = AdvisorResponse(
            tier=Tier.REPLACEMENT, intent=Intent.CHECK_LEGALITY,
            answer=ReplacementAnswer(
                subject="C-2087", legal=False,
                verdicts=[RuleVerdict(rule_id="RULE-DUTY-02", status="FAIL",
                                      detail="would exceed 60h/7d by 1h20m")]),
            trace=[TraceEntry(tool="check_legality", result={"legal": False})],
        )
        out = explainer.render(r)
        assert "would breach" in out
        assert "is legal" not in out


class TestLegalityAnswersAreNotDiscarded:
    """"Does any rule breach?" computed the right verdict and then reported
    "No data was returned" — build_answer only read find_options and ripple,
    so every check_legality result was thrown away."""

    def _response(self, legal, verdicts):
        from agent.advisor import build_answer
        from agent.router import route
        from agent.schemas import TraceEntry

        trace = [TraceEntry(tool="check_legality",
                            result={"crew_id": "C-2087", "legal": legal,
                                    "verdicts": verdicts})]
        return build_answer(route("If C-2087 covers P-2291, does any rule breach?"), trace)

    def test_the_verdict_reaches_the_answer_object(self):
        body = self._response(False, [{"rule_id": "RULE-DUTY-02", "status": "FAIL",
                                       "detail": "over by 1h20m"}])
        assert body.subject == "C-2087" and body.legal is False
        assert body.verdicts[0].failed

    def test_it_counts_as_content(self):
        from agent import explainer

        assert explainer.has_content(
            self._response(True, [{"rule_id": "RULE-FDP-01", "status": "PASS"}]))


class TestClarifyingQuestionsReachTheController:
    """A tool can end a turn by asking something only a human can settle.

    "DX412 operates on three dates — which do you mean?" was being answered by
    the model itself: it checked all three and narrated whichever it preferred,
    so the same question gave different answers on different runs. One run led
    with CERT-06 on the 19th, the next with DUTY-02 on the 15th. Both true,
    neither asked for.
    """

    def _port_that_asks(self, code="AMBIGUOUS_QUERY"):
        from agent.tools import PlaceholderToolPort, ToolError

        class Asking(PlaceholderToolPort):
            def check_legality(self, crew_id, pairing_id=None, **kw):
                raise ToolError(code, "DX412 operates on three dates. Which?")

        return Asking()

    def _eager_llm(self):
        """A model that tries to answer the question itself."""
        from agent.llm import LLMResponse, PlaceholderLLM, ToolCall

        return PlaceholderLLM([
            LLMResponse(tool_calls=[ToolCall("1", "check_legality",
                                             {"crew_id": "C-2087",
                                              "pairing_id": "P-2291"})],
                        stop_reason="tool_use")] * 6)

    def test_the_loop_stops_on_a_clarifying_question(self):
        llm = self._eager_llm()
        r = Advisor(port=self._port_that_asks(), llm=llm).ask(
            "If C-2087 covers P-2291, does any rule breach?")
        assert len(r.trace) == 1, "kept calling tools past a question for the human"

    def test_the_question_is_the_answer(self):
        r = Advisor(port=self._port_that_asks(), llm=self._eager_llm()).ask(
            "If C-2087 covers P-2291, does any rule breach?")
        assert "Which?" in r.narrative
        assert r.confidence is Confidence.HIGH

    def test_a_needs_confirmation_halts_too(self):
        r = Advisor(port=self._port_that_asks("NEEDS_CONFIRMATION"),
                    llm=self._eager_llm()).ask(
            "If C-2087 covers P-2291, does any rule breach?")
        assert len(r.trace) == 1

    def test_an_ordinary_failure_is_not_treated_as_a_question(self):
        """A missing capability is not something the desk can answer, so it
        must not end the turn as though we had asked them something."""
        from agent.tools import PlaceholderToolPort, ToolError

        class Broken(PlaceholderToolPort):
            def check_legality(self, crew_id, pairing_id=None, **kw):
                raise ToolError("INTERNAL", "needs the rules engine")

        r = Advisor(port=Broken(), llm=self._eager_llm()).ask(
            "If C-2087 covers P-2291, does any rule breach?")
        assert "needs the rules engine" in r.narrative
        assert r.confidence is Confidence.LOW, "a capability gap read as confident"


class TestCertificationWindow:
    """Q04 — the compliance listing. Tier 1 is the mandatory tier, and this is
    the question that used to route correctly and then run nothing."""

    def _expected(self):
        import json
        from pathlib import Path

        path = Path("crew-ops-advisor-dataset/data/questions.json")
        if not path.exists():
            pytest.skip("dataset not vendored")
        questions = json.loads(path.read_text())
        return [q for q in questions if q["question_id"] == "Q04"][0]

    def test_seed_builds_the_interval_the_answer_key_describes(self):
        """The key says: valid_to between 2026-09-15 and 2026-10-15."""
        calls = seed_calls(route(self._expected()["prompt"]))
        assert [c.name for c in calls] == ["lookup"]
        assert calls[0].args["filters"] == {
            "valid_to": {"gte": "2026-09-15", "lte": "2026-10-15"}
        }

    def test_matches_the_answer_key_exactly(self):
        question = self._expected()
        rows = Advisor(port=PlaceholderToolPort(), llm=PlaceholderLLM()).ask(
            question["prompt"])
        returned = {
            (r["crew_id"], r["cert_type"], str(r["valid_to"]))
            for entry in rows.trace if entry.tool == "lookup"
            for r in entry.result
        }
        assert returned == {
            (r["crew_id"], r["cert_type"], r["valid_to"])
            for r in question["expected_answer"]
        }

    def test_no_horizon_means_no_invented_window(self):
        """A window nobody asked for silently changes who is on the list."""
        calls = seed_calls(route("What certifications does C-1042 hold?"))
        assert calls[0].args["filters"] == {"crew_id": "C-1042"}


class TestFilterRanges:
    def test_unknown_operator_is_rejected_not_ignored(self):
        """A dropped bound widens the result set with nothing to notice it by."""
        from agent.tools import ToolError, resolve_filters

        with pytest.raises(ToolError, match="unknown filter operator"):
            resolve_filters("certifications", {"valid_to": {"before": "2026-10-15"}},
                            {"valid_to"})

    def test_bounds_are_inclusive_both_ends(self):
        from agent.tools import row_matches

        want = {"gte": "2026-09-15", "lte": "2026-10-15"}
        assert row_matches({"valid_to": "2026-09-15"}, "valid_to", want)
        assert row_matches({"valid_to": "2026-10-15"}, "valid_to", want)
        assert not row_matches({"valid_to": "2026-10-16"}, "valid_to", want)

    def test_a_missing_column_does_not_satisfy_a_range(self):
        from agent.tools import row_matches

        assert not row_matches({}, "valid_to", {"lte": "2026-10-15"})

    def test_list_valued_columns_are_containment(self):
        """`ratings` holds a list; asking for A320 means "holds an A320 rating",
        which equality answered as no-one. Postgres already did containment."""
        from agent.tools import row_matches

        assert row_matches({"ratings": ["A320", "ATR72"]}, "ratings", "A320")


class TestNotification:
    """Q36 — the callout message. The one place a model is the right tool for
    the job, which is why every fact under it comes from the roster."""

    def _brief(self):
        return PlaceholderToolPort().notification_brief("C-3310", "P-2291")

    def test_routes_away_from_cover(self):
        """"Draft the callout notification" contains "callout", which is a
        cover request in every other pattern in the table."""
        r = route("Draft the callout notification to C-3310 for covering P-2291.")
        assert r.intent is Intent.DRAFT_NOTIFICATION
        assert seed_calls(r)[0].name == "notification_brief"

    def test_times_come_from_the_roster(self):
        brief = self._brief()
        day1, day2 = brief["days"]
        assert (day1["report_utc"], day1["report_station"]) == ("06:00Z", "BLR")
        assert day1["flights"] == ["DX412", "DX413", "DX588"]
        assert day1["overnight_station"] == "DEL"
        assert (day2["report_utc"], day2["report_station"]) == ("04:00Z", "DEL")
        assert day2["flights"] == ["DX589", "DX590", "DX591"]

    def test_last_day_does_not_overnight(self):
        """The crew go home. An overnight on the final day would book a hotel
        nobody needs and tell the crew to stay put."""
        assert self._brief()["days"][-1]["overnight_station"] is None

    def test_acknowledgement_deadline_is_derived_from_reachability(self):
        """06:00Z report, 45 minutes to reach the airport -> 05:15Z. The last
        moment a "no" is still actionable, not a round number."""
        brief = self._brief()
        assert brief["reachability_minutes"] == 45
        assert brief["acknowledge_by_utc"] == "05:15Z"

    def test_covers_every_item_the_answer_key_requires(self):
        from agent import notify

        message = notify.render(self._brief())
        for required in ("C-3310", "P-2291", "06:00Z", "BLR crew room",
                         "DX412/DX413/DX588", "DEL", "04:00Z",
                         "DX589/DX590/DX591", "acknowledge", "Crew Control"):
            assert required in message, required

    def test_invents_no_contact_details(self):
        """A plausible-looking phone number is exactly the kind of invention
        this system exists not to make; the dataset has none."""
        import re

        from agent import notify

        message = notify.render(self._brief())
        assert not re.search(r"\+?\d[\d\s-]{7,}", message)

    def test_message_is_verifiable_against_its_own_brief(self):
        from agent.schemas import AdvisorResponse, NotificationAnswer, Tier, TraceEntry
        from agent.verifier import verify

        brief = self._brief()
        response = AdvisorResponse(
            tier=Tier.CONSEQUENCE, intent=Intent.DRAFT_NOTIFICATION,
            answer=NotificationAnswer(brief=brief),
            trace=[TraceEntry(tool="notification_brief", result=brief)],
        )
        from agent import explainer

        assert verify(explainer.render(response), response.trace).ok

    def test_unknown_pairing_is_refused_not_improvised(self):
        from agent.tools import ToolError

        with pytest.raises(ToolError, match="P-9999"):
            PlaceholderToolPort().notification_brief("C-3310", "P-9999")


class TestLookupTable:
    """Tier 1 is the mandatory tier and the first thing anyone will type at
    this. It is worth reading well."""

    def _answer(self, rows):
        from agent.schemas import AdvisorResponse, LookupAnswer, Tier, TraceEntry

        return AdvisorResponse(
            tier=Tier.LOOKUP, intent=Intent.LOOKUP_CREW,
            answer=LookupAnswer(rows=rows),
            trace=[TraceEntry(tool="lookup", result=rows)],
        )

    def test_columns_align_across_rows(self):
        from agent import explainer

        out = explainer.render(self._answer([
            {"crew_id": "C-1", "rank": "Captain"},
            {"crew_id": "C-1042", "rank": "First Officer"},
        ]))
        body = [ln for ln in out.splitlines() if "C-1" in ln]
        assert len({ln.index("C-1") for ln in body}) == 1, "ragged left edge"
        starts = {body[0].index("Captain"), body[1].index("First Officer")}
        assert len(starts) == 1, "ragged second column"

    def test_a_column_missing_from_the_first_row_still_appears(self):
        """Backends differ in which optional fields they populate. A column
        dropped because row one lacked it is a fact withheld."""
        from agent import explainer

        out = explainer.render(self._answer([{"crew_id": "C-1"},
                                             {"crew_id": "C-2", "base": "BLR"}]))
        assert "base" in out and "BLR" in out

    def test_identity_columns_come_first(self):
        from agent import explainer

        out = explainer.render(self._answer([{"seniority": 14, "crew_id": "C-1042"}]))
        header = [ln for ln in out.splitlines() if "crew_id" in ln][0]
        assert header.index("crew_id") < header.index("seniority")

    def test_a_wide_constant_column_is_stated_once_not_repeated(self):
        """reserve_pool.dates is the same 82 characters on every row, which
        pushed the on-call windows off the side of the screen."""
        from agent import explainer

        dates = ["2026-09-%02d" % d for d in range(14, 21)]
        out = explainer.render(self._answer([
            {"crew_id": "C-1", "dates": dates, "oncall_start_utc": "04:00"},
            {"crew_id": "C-2", "dates": dates, "oncall_start_utc": "06:00"},
        ]))
        assert out.count("2026-09-14") == 1, "repeated on every row"
        assert "every row — dates" in out, "stated, not silently dropped"
        assert "04:00" in out and "06:00" in out

    def test_values_are_never_truncated(self):
        """A shortened id reads as a different id, and the verifier would
        rightly refuse to source it."""
        from agent import explainer
        from agent.verifier import verify

        response = self._answer([{"flight_id": "DX412-2026-09-15"}])
        out = explainer.render(response)
        assert "DX412-2026-09-15" in out
        assert verify(out, response.trace).ok
