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

    def test_system_prompt_inlines_exemplars(self):
        prompt = system_prompt(Intent.FIND_REPLACEMENT)
        assert "Worked examples" in prompt
        assert "This request" in prompt

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
