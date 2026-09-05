"""Multi-turn state — what makes this an advisor rather than a report generator.

`Advisor.ask()` is stateless: every question starts from nothing. That is fine
for a lookup and wrong for a desk. A controller does not ask one question, read
a table and act — they interrogate the recommendation:

    "C-1042 is sick"          -> ranked options
    "why not C-2087?"         -> because DUTY-02 by 1h20m on the 15th
    "what about C-2210?"      -> legal, but ₹41,200 and a 3h delay
    "what if I delay 40 min?" -> re-run against the delayed duty
    "go with C-3310"          -> decision recorded

Two things make that cheap. Most follow-ups are answerable from data **already
on the table** — a candidate search returns 22 exclusions each with its reason,
so "why not X" needs no new tool call at all. And the entities carry forward,
so "what about C-2210?" inherits the pairing from the turn before it.

It also closes a hole: "did you mean C-1042?" is a question, and without state
there was nowhere for the answer to go.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from agent.advisor import Advisor, AdvisorConfig
from agent.entities import CREW_RE, Entities, extract
from agent.llm import LLM
from agent.schemas import (
    AdvisorResponse,
    Confidence,
    ConsequenceAnswer,
    Intent,
    ReplacementAnswer,
    Tier,
    TraceEntry,
)
from agent.tools import ToolPort

# --------------------------------------------------------------------------
# What a follow-up looks like
# --------------------------------------------------------------------------

AFFIRM_RE = re.compile(
    r"^\s*(yes|yeah|yep|yup|correct|right|that one|the first|confirm(ed)?|"
    r"go ahead|do it|ok(ay)?)\b", re.I)
DENY_RE = re.compile(r"^\s*(no|nope|neither|none|wrong)\b", re.I)

WHY_NOT_RE = re.compile(
    r"\bwhy (not|isn'?t|wasn'?t|can'?t|didn'?t|is|was)\b|\bwhat'?s wrong with\b|"
    r"\bwhy exclude|\bwhy drop|"
    # A bare "why C-3310?" asks the same thing as "why is C-3310 the pick?"
    r"\bwhy\s+(?:[A-Za-z]-\d{4}|him|her|them|that|it)\b", re.I)
WHAT_ABOUT_RE = re.compile(
    r"\bwhat about\b|\bhow about\b|\band\b\s+[Cc]-\d{4}|\bconsider\b", re.I)
DECIDE_RE = re.compile(
    r"\b(go with|use|take|assign|book|call out|pick|choose|i'?ll take)\b", re.I)
COST_RE = re.compile(r"\bwhat does (that|it) cost\b|\bhow much\b|\bcost of\b", re.I)

# Words that mean "the thing we were just talking about".
ANAPHORA_RE = re.compile(
    r"\b(him|her|them|they|that|those|it|this|the same|instead)\b", re.I)


@dataclass(slots=True)
class Exchange:
    """One question and what came back."""

    query: str
    response: AdvisorResponse
    entities: Entities

    @property
    def options(self) -> list[Any]:
        body = self.response.answer
        return list(getattr(body, "options", []) or [])

    @property
    def excluded(self) -> list[dict[str, Any]]:
        body = self.response.answer
        return list(getattr(body, "excluded", []) or [])

    @property
    def pending_rank(self) -> tuple[str, str] | None:
        """(crew_id, real rank) when the last turn queried a stated rank.

        "FO C-2087" names a real person under the wrong seat. Confirming does
        not swap the id — it drops the wrong rank and proceeds with the roster's.
        """
        for entry in self.response.trace:
            if entry.tool == "roster_check" and entry.error:
                m = re.search(r"(C-\d{4}) is a ([A-Za-z ]+?), not a", entry.error)
                if m:
                    return m.group(1), m.group(2).strip()
        return None

    @property
    def pending_detail(self) -> str | None:
        """A detail the last turn asked for and could not proceed without.

        "DX412 operates on three dates, which do you mean?" is a question. If
        the next turn supplies one and nothing carries it back to the original
        query, the controller answers into a void — the same hole confirmation
        had.
        """
        for entry in self.response.trace:
            if entry.error and entry.error.startswith("AMBIGUOUS_QUERY"):
                if "date" in entry.error.lower():
                    return "date"
        return None

    @property
    def pending_confirmation(self) -> str | None:
        """The id we asked the controller to confirm, if we asked."""
        for entry in self.response.trace:
            if entry.error and entry.error.startswith("NEEDS_CONFIRMATION"):
                if ids := CREW_RE.findall(entry.error):
                    # The suggestion, not the id they typed.
                    typed = set(self.entities.crew_ids)
                    return next((i for i in ids if i not in typed), None)
        return None


@dataclass
class Conversation:
    """A controller's session. Carries context so follow-ups mean something."""

    port: ToolPort | None = None
    llm: LLM | None = None
    cfg: AdvisorConfig | None = None
    history: list[Exchange] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._advisor = Advisor(port=self.port, llm=self.llm, cfg=self.cfg)

    @property
    def last(self) -> Exchange | None:
        return self.history[-1] if self.history else None

    @property
    def last_search(self) -> Exchange | None:
        """The most recent turn that actually produced candidates.

        Not the previous turn — by the time a controller says "go with
        C-3310" they may have asked two clarifying questions since the search,
        and the options are still the ones on the table. Looking only one turn
        back loses the thread exactly when a decision is being made.
        """
        for exchange in reversed(self.history):
            if exchange.options or exchange.excluded:
                return exchange
        return None

    def candidate(self, crew_id: str) -> tuple[Exchange, Any, str] | None:
        """Find a crew member in the last search: (turn, record, where)."""
        search = self.last_search
        if search is None:
            return None
        for option in search.options:
            if getattr(option, "crew_id", None) == crew_id:
                return search, option, "option"
        for row in search.excluded:
            if row.get("crew_id") == crew_id:
                return search, row, "excluded"
        return None

    # -- context carry-forward --------------------------------------------

    def _inherit(self, query: str, ents: Entities) -> tuple[str, Entities]:
        """Fill in what this turn leaves implicit from the turn before it.

        "what about C-2210?" names a person and nothing else; the pairing,
        role and date all come from the question it follows.
        """
        prior = self.last
        if prior is None:
            return query, ents

        for field_name in ("pairing_ids", "flight_ids", "flight_nos",
                           "dates", "roles", "stations"):
            if not getattr(ents, field_name):
                setattr(ents, field_name, list(getattr(prior.entities, field_name)))

        # Only inherit the crew id when this turn names nobody — otherwise
        # "what about C-2210" would still be about C-1042.
        if not ents.crew_ids and ANAPHORA_RE.search(query):
            ents.crew_ids = list(prior.entities.crew_ids)

        return query, ents

    # -- follow-ups answerable from the previous turn ----------------------

    def _answer_about(self, crew_id: str) -> AdvisorResponse | None:
        """What we already know about a candidate, from the search we ran.

        Serves "why not X", "what about X" and "is X any good" alike — they
        are the same question, and the answer is sitting in the last search.
        Re-running it to rediscover the reason would be slower and no more
        correct.
        """
        found = self.candidate(crew_id)
        if found is None:
            return None
        search, record, where = found

        if where == "excluded":
            return self._from_prior(
                f"{crew_id} was excluded: {record.get('reason', 'no reason recorded')}",
                search, cites=record.get("rules", []))

        options = search.options
        top = options[0] if options else None
        if record is top:
            return self._from_prior(
                f"{crew_id} *is* the recommendation — "
                f"₹{record.cost_inr:,}"
                + (f", {record.delay_hours}h delay." if record.delay_hours else ", no delay."),
                search)

        text = (f"{crew_id} is legal, ranked #{getattr(record, 'rank', '?')}: "
                f"₹{record.cost_inr:,}")
        if record.delay_hours:
            text += f" and delays the first departure by {record.delay_hours}h"
        if top is not None:
            text += f", against ₹{top.cost_inr:,} for {top.crew_id}."
        return self._from_prior(text, search)

    def _answer_decision(self, crew_id: str) -> AdvisorResponse | None:
        """Record what the controller chose. The desk decides; we advise."""
        found = self.candidate(crew_id)
        if found is None:
            return None
        prior, chosen, where = found

        if where == "excluded":
            # Refuse to book someone the rules engine rejected, and say why.
            return self._from_prior(
                f"I cannot record {crew_id}: they were excluded — "
                f"{chosen.get('reason', 'no reason recorded')}",
                prior, cites=chosen.get("rules", []))

        self.decisions.append({
            "crew_id": crew_id,
            "action": chosen.action,
            "cost_inr": chosen.cost_inr,
            "query": prior.query,
        })
        recommended = prior.options[0] if prior.options else None
        text = f"Recorded: {chosen.action} — ₹{chosen.cost_inr:,}."
        if recommended is not None and recommended.crew_id != crew_id:
            text += (f"\n\nNote this is not the cheapest option: "
                     f"{recommended.crew_id} was ₹{recommended.cost_inr:,}.")
        return self._from_prior(text, prior)

    def _from_prior(self, text: str, prior: Exchange,
                    cites: list[str] | None = None) -> AdvisorResponse:
        """An answer built from a previous turn's evidence.

        The trace is carried over so the verifier still has something to check
        against — a follow-up is not exempt from sourcing just because it
        needed no new tool call.
        """
        from agent.schemas import Citation

        return AdvisorResponse(
            tier=prior.response.tier,
            intent=prior.response.intent,
            entities=prior.response.entities,
            answer=prior.response.answer,
            narrative=text,
            citations=[Citation(kind="rule", id=r) for r in (cites or [])],
            confidence=Confidence.HIGH,
            trace=prior.response.trace,
        )

    # -- the turn ----------------------------------------------------------

    def ask(self, query: str) -> AdvisorResponse:
        ents = extract(query)
        prior = self.last

        # 1. Confirming an id we asked about. Without this, "did you mean
        #    C-1042?" is a question with nowhere for the answer to go.
        if prior is not None and (pending := prior.pending_confirmation):
            if AFFIRM_RE.match(query) or query.strip().upper() == pending:
                corrected = prior.query
                for wrong in prior.entities.crew_ids:
                    corrected = corrected.replace(wrong, pending)
                if corrected == prior.query:
                    corrected = f"{pending} {prior.query}"
                return self._record(corrected, self._advisor.ask(corrected))
            if DENY_RE.match(query):
                return self._record(query, self._from_prior(
                    "Understood — not that one. Give me the correct id and I "
                    "will run it.", prior))

        # 2. Confirming a rank we queried — proceed with the roster's, and
        #    strip the wrong one so it cannot be picked up again.
        if prior is not None and (pending_rank := prior.pending_rank):
            crew_id, real_rank = pending_rank
            if AFFIRM_RE.match(query) or real_rank.lower() in query.lower():
                from agent.entities import STATED_RANK_RE

                corrected = STATED_RANK_RE.sub(
                    lambda m: f"{real_rank} {m.group(2)}", prior.query)
                return self._record(corrected, self._advisor.ask(corrected))
            if DENY_RE.match(query):
                return self._record(query, self._from_prior(
                    f"Understood. Give me the right crew id and I will run it — "
                    f"{crew_id} is the {real_rank}.", prior))

        # 3. Supplying a detail the previous turn asked for. Re-run the
        #    original question with it rather than treating the fragment as a
        #    new query — "on 2026-09-15" alone means nothing.
        if prior is not None and prior.pending_detail == "date" and ents.dates:
            resumed = f"{prior.query} on {ents.dates[0]}"
            return self._record(resumed, self._advisor.ask(resumed))

        # 4. Follow-ups the previous turn already answered.
        if prior is not None:
            target = ents.crew_ids[0] if ents.crew_ids else None

            if target and (WHY_NOT_RE.search(query) or WHAT_ABOUT_RE.search(query)):
                if answer := self._answer_about(target):
                    return self._record(query, answer)

            if DECIDE_RE.search(query) and target:
                if answer := self._answer_decision(target):
                    return self._record(query, answer)

        # 5. A new question, with whatever this turn left implicit filled in.
        query_for_agent = query
        if prior is not None and (WHAT_ABOUT_RE.search(query)
                                  or ANAPHORA_RE.search(query)
                                  or not ents.to_dict()):
            _, ents = self._inherit(query, ents)
            query_for_agent = self._rewrite(query, ents)

        return self._record(query, self._advisor.ask(query_for_agent), ents)

    @staticmethod
    def _rewrite(query: str, ents: Entities) -> str:
        """Make an implicit follow-up self-contained.

        The advisor is stateless by design, so context is resolved here and
        handed down as a complete question rather than threading history
        through every layer.
        """
        parts = [query]
        if ents.pairing_ids and ents.pairing_ids[0] not in query:
            parts.append(f"(pairing {ents.pairing_ids[0]})")
        if ents.roles and ents.roles[0].lower() not in query.lower():
            parts.append(f"(role {ents.roles[0]})")
        if ents.dates and ents.dates[0] not in query:
            parts.append(f"(on {ents.dates[0]})")
        return " ".join(parts)

    def _record(self, query: str, response: AdvisorResponse,
                ents: Entities | None = None) -> AdvisorResponse:
        self.history.append(
            Exchange(query=query, response=response, entities=ents or extract(query)))
        return response
