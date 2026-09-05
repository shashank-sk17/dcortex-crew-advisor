"""Multi-turn state — what makes this an advisor rather than a report generator.

A controller does not read a table and act; they interrogate the
recommendation. Every test here is a question one would actually ask next.
"""

from __future__ import annotations

import pytest

from agent.conversation import Conversation
from agent.llm import PlaceholderLLM
from agent.schemas import (AdvisorResponse, FunnelStage, Intent, Option,
                           ReplacementAnswer, Tier, TraceEntry)


def _search_response() -> AdvisorResponse:
    """A completed candidate search, as the first turn would leave it."""
    return AdvisorResponse(
        tier=Tier.REPLACEMENT, intent=Intent.FIND_REPLACEMENT,
        answer=ReplacementAnswer(
            options=[
                Option("Assign Captain C-3310 (reserve callout)", "C-3310",
                       True, cost_inr=18500, rank=1),
                Option("Assign Captain C-2210 (deadhead)", "C-2210",
                       True, cost_inr=41200, delay_hours=3.0, rank=2),
            ],
            excluded=[{"crew_id": "C-2087",
                       "reason": "would exceed 60h/7d by 1h20m on 2026-09-15",
                       "rules": ["RULE-DUTY-02"]}],
            funnel=[FunnelStage("considered", 27), FunnelStage("legal", 2)],
        ),
        trace=[TraceEntry(tool="find_options", result={"crew_id": "C-3310"})],
    )


@pytest.fixture
def convo():
    c = Conversation(llm=PlaceholderLLM())
    c._record("C-1042 is sick", _search_response())
    return c


class TestFollowUpsFromPriorData:
    """The exclusion reason is already on the table. Re-running the search to
    rediscover it would be slower and no more correct."""

    def test_why_not_gives_the_actual_breach(self, convo):
        r = convo.ask("why not C-2087?")
        assert "60h/7d by 1h20m" in r.narrative
        assert any(c.id == "RULE-DUTY-02" for c in r.citations)

    def test_it_costs_no_new_tool_call(self, convo):
        before = len(convo.history[0].response.trace)
        convo.ask("why not C-2087?")
        assert len(convo.history[-1].response.trace) == before

    def test_what_about_ranks_a_legal_option(self, convo):
        r = convo.ask("what about C-2210?")
        assert "41,200" in r.narrative and "18,500" in r.narrative

    def test_asking_about_the_pick_says_so(self, convo):
        assert "is the recommendation" in convo.ask("why C-3310?").narrative.replace("*", "")


class TestDecisions:
    def test_a_choice_is_recorded(self, convo):
        convo.ask("go with C-3310")
        assert convo.decisions[0]["crew_id"] == "C-3310"

    def test_choosing_a_dearer_option_is_flagged_not_blocked(self, convo):
        """The desk decides. We note the cost difference and record it."""
        r = convo.ask("go with C-2210")
        assert convo.decisions[0]["crew_id"] == "C-2210"
        assert "not the cheapest" in r.narrative

    def test_an_excluded_candidate_is_refused_with_the_reason(self, convo):
        r = convo.ask("go with C-2087")
        assert not convo.decisions
        assert "cannot record" in r.narrative and "60h/7d" in r.narrative


class TestContextSurvivesIntermediateTurns:
    def test_a_decision_still_lands_after_clarifying_questions(self, convo):
        """By the time a controller decides, the search may be several turns
        back. Looking only at the previous turn loses the thread exactly when
        it matters."""
        convo.ask("why not C-2087?")
        convo.ask("what about C-2210?")
        convo.ask("go with C-3310")
        assert convo.decisions[0]["crew_id"] == "C-3310"

    def test_the_candidates_stay_reachable_after_a_follow_up(self, convo):
        """A follow-up carries the prior answer forward so the verifier keeps
        its evidence and the UI keeps the funnel — so the options are still
        found, whichever turn holds them."""
        convo.ask("why not C-2087?")
        search = convo.last_search
        assert search is not None
        assert [o.crew_id for o in search.options] == ["C-3310", "C-2210"]


class TestConfirmation:
    """"Did you mean C-1042?" is a question. Without state there was nowhere
    for the answer to go."""

    def _asked(self):
        c = Conversation(llm=PlaceholderLLM())
        c._record("C-1024 is sick", AdvisorResponse(
            tier=Tier.REPLACEMENT, intent=Intent.FIND_REPLACEMENT,
            answer=ReplacementAnswer(),
            trace=[TraceEntry(tool="find_options",
                              error="NEEDS_CONFIRMATION: There is no crew C-1024. "
                                    "Did you mean C-1042 (Captain, BLR)?")],
        ))
        return c

    def test_the_pending_id_is_the_suggestion_not_the_typo(self):
        assert self._asked().last.pending_confirmation == "C-1042"

    def test_declining_asks_for_the_right_id(self):
        assert "correct id" in self._asked().ask("no").narrative

    def test_nothing_is_pending_after_a_normal_answer(self, convo):
        assert convo.last.pending_confirmation is None


class TestNoPriorContext:
    def test_a_follow_up_with_no_history_is_not_answered_from_nothing(self):
        """A bare "why not C-2087?" as the first thing said has no search to
        read from, and must not invent one."""
        c = Conversation(llm=PlaceholderLLM())
        r = c.ask("why not C-2087?")
        assert "60h/7d" not in r.narrative


class TestStatedRankIsCheckedAgainstTheRoster:
    """dCortex's own problem statement says "FO C-2087" and their dataset
    README flags it as an erratum — C-2087 is a Captain.

    So a judge may well type the wrong rank, because their document told them
    to. Accepting it silently answers about the wrong seat; the roster knows,
    so it should say.
    """

    def test_only_a_descriptive_rank_is_checked(self):
        from agent.entities import stated_ranks

        assert stated_ranks("If I move FO C-2087 onto DX412") == [("C-2087", "First Officer")]
        # A role naming the seat to fill asserts nothing about a person.
        assert stated_ranks("who can cover P-2291 as Captain") == []

    def test_a_wrong_rank_stops_and_asks(self):
        from agent.advisor import Advisor
        from agent.tools_fixtures import FixtureToolPort

        r = Advisor(port=FixtureToolPort(), llm=PlaceholderLLM()).ask(
            "If I move FO C-2087 onto DX412, does anyone breach a duty limit?")
        assert "is a Captain, not a First Officer" in r.narrative
        assert len(r.trace) == 1, "ran tools before resolving who was meant"

    def test_the_right_rank_passes_through(self):
        from agent.advisor import Advisor
        from agent.tools_fixtures import FixtureToolPort

        r = Advisor(port=FixtureToolPort(), llm=PlaceholderLLM()).ask(
            "Captain C-1042 calls in sick")
        assert "not a" not in r.narrative

    def test_confirming_proceeds_with_the_roster_rank(self):
        from agent.tools_fixtures import FixtureToolPort

        c = Conversation(port=FixtureToolPort(), llm=PlaceholderLLM())
        c.ask("If I move FO C-2087 onto DX412, does anyone breach a duty limit?")
        c.ask("yes")
        assert "FO C-2087" not in c.history[-1].query
        assert "Captain C-2087" in c.history[-1].query

    def test_declining_names_the_real_rank(self):
        from agent.tools_fixtures import FixtureToolPort

        c = Conversation(port=FixtureToolPort(), llm=PlaceholderLLM())
        c.ask("If I move FO C-2087 onto DX412, does anyone breach a duty limit?")
        assert "C-2087 is the Captain" in c.ask("no").narrative


class TestCrewAreNamed:
    """A controller phones a person, not an id. One spelling everywhere:
    `Rank Name (C-XXXX)`."""

    def test_the_helper_puts_the_id_in_brackets(self):
        from agent.explainer import who

        assert who("C-1042", "A. Nair", "Captain") == "Captain A. Nair (C-1042)"

    def test_it_falls_back_to_the_id_rather_than_inventing_a_name(self):
        from agent.explainer import who

        assert who("C-1042") == "C-1042"
        assert who(None) == ""

    def test_an_option_rank_is_not_mistaken_for_a_job_rank(self):
        """`Option.rank` is the position in the ranking and cannot be renamed
        — the answer keys compare against it (DECISIONS.md #10)."""
        from agent.conversation import _name_of
        from agent.schemas import Option

        option = Option(action="Assign", crew_id="C-3310", legal=True,
                        rank=1, name="D. Reddy")
        assert _name_of(option, "C-3310") == "D. Reddy (C-3310)"

    def test_an_exclusion_row_is_named(self):
        from agent.conversation import _name_of

        row = {"crew_id": "C-2087", "name": "R. Iyer", "rank": "Captain"}
        assert _name_of(row, "C-2087") == "Captain R. Iyer (C-2087)"


class TestNamedPeople:
    """The system writes "Captain A. Nair (C-1042)", so a controller writes
    "Nair" back. If that is not understood the query runs with no crew filter
    and answers a question about one person with all 150 of them."""

    def _convo(self):
        from agent.conversation import Conversation
        from agent.tools import PlaceholderToolPort

        return Conversation(port=PlaceholderToolPort())

    def test_a_shared_surname_asks_which(self):
        """Every surname in this dataset is shared — Nair is seven people."""
        r = self._convo().ask("is Nair available?")
        assert r.awaiting == "confirmation"
        assert "C-1042" in r.narrative and "C-5820" in r.narrative
        assert "will not guess" in r.narrative

    def test_even_a_full_name_can_be_two_people(self):
        """A. Nair is a Captain and a Cabin Crew member, both at BLR."""
        r = self._convo().ask("is A. Nair available?")
        assert r.awaiting == "confirmation"
        assert "C-1042" in r.narrative and "C-3145" in r.narrative

    def test_a_rank_narrows_it_to_one(self):
        c = self._convo()
        r = c.ask("is Captain N. Nair available?")
        assert r.awaiting is None
        assert any("C-5820" in str(e.args) or "C-5820" in str(e.result)
                   for e in r.trace)

    def test_context_beats_the_roster(self):
        """Right after discussing C-1042, "Nair" means that one."""
        c = self._convo()
        c.ask("C-1042 is sick, who do I use?")
        r = c.ask("is Nair available?")
        assert r.awaiting is None, "asked which, when the last turn had said"

    def test_a_near_miss_name_suggests_rather_than_lists_everyone(self):
        r = self._convo().ask("is Nayar available?")
        assert r.awaiting == "detail"
        assert "Nair" in r.narrative
        assert "150" not in r.narrative

    def test_an_unknown_name_says_so_instead_of_dumping_the_roster(self):
        r = self._convo().ask("is Smithson available?")
        assert r.awaiting == "detail"
        assert "No crew called Smithson" in r.narrative
        assert "records." not in r.narrative

    def test_a_capitalised_non_name_does_not_derail_the_question(self):
        """"Sep" is not a person. Only words the roster recognises are."""
        r = self._convo().ask("Is A. Nair on duty on 15 Sep?")
        assert "Sep" not in (r.narrative[:60])

    def test_an_unfiltered_crew_lookup_is_never_an_answer(self):
        """150 rows is not a reply to anything a controller asked."""
        from agent.advisor import seed_calls
        from agent.router import route

        assert seed_calls(route("list all crew")) == []
        assert seed_calls(route("Which Captains are based at BLR?"))
