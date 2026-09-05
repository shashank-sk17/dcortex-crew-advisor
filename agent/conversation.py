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

from agent import explainer
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
COST_RE = re.compile(
    r"\bwhat does (that|it) cost\b|\bhow much\b|\bcost of\b"
    r"|\bwhat (will|would|does|did) .{0,40}\bcost\b|\bcost to\b", re.I)

# A question is never an instruction, however many decision verbs it contains.
#
# "What will it cost to pick Das?" contains "pick", which is enough for
# DECIDE_RE — so asking the price BOOKED the crew member and replied
# "Recorded: … ₹9,500". Recording an assignment nobody made is the worst thing
# this system can do quietly, so the decision path now requires an actual
# instruction: "assign C-4809", not "should I assign C-4809?".
QUESTION_RE = re.compile(
    r"\?\s*$"
    r"|^\s*(what|why|how|which|who|whom|whose|when|where|can|could|would|"
    r"should|shall|is|are|was|were|does|do|did|will|may|might)\b",
    re.I)

# "Next cheapest option?", "anything cheaper?", "what else have I got?" — a
# question about the ranking already on the table, not a new search. The turn
# that produced the options costed every one of them, so this needs no tool.
NEXT_OPTION_RE = re.compile(
    r"\b(next|other|another|alternative|cheaper|cheapest|second|third|else)\b"
    r".{0,30}\b(option|choice|crew|one|s)?\b|\bwhat else\b|\banything cheaper\b",
    re.I)

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


def _is_bare_id(query: str) -> str | None:
    """True when the controller typed an id and essentially nothing else.

    "C-3310" answers a "which one?"; "what does C-3310 cost" is a new question
    that happens to name one, and must not be rewritten into the old query.
    """
    stripped = query.strip().strip(".?!,")
    return CREW_RE.fullmatch(stripped) is not None


def _name_of(record: Any, crew_id: str) -> str:
    """`Captain A. Nair (C-1042)` from an option or an exclusion row.

    Both shapes turn up here — options are dataclasses, exclusions are plain
    dicts — and a follow-up should read the same either way.
    """
    get = record.get if isinstance(record, dict) else (
        lambda k, d=None: getattr(record, k, d))
    # `rank` means two different things here. On an exclusion row it is the
    # job — "Captain". On an Option it is the position in the ranking, an int,
    # and it cannot be renamed because the answer keys compare against it
    # (DECISIONS.md #10). So only a string is a job rank.
    job = get("rank")
    return explainer.who(crew_id, get("name"), job if isinstance(job, str) else None)


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

    def candidate_ids(self) -> set[str]:
        """Everyone the last search put on the table, offered or ruled out."""
        search = self.last_search
        if search is None:
            return set()
        ids = {cid for o in search.options
               if (cid := getattr(o, "crew_id", None))}
        ids |= {cid for r in search.excluded if (cid := r.get("crew_id"))}
        return ids

    def recommended_id(self) -> str | None:
        """The candidate the last search actually put first."""
        search = self.last_search
        if search is None or not search.options:
            return None
        return getattr(search.options[0], "crew_id", None)

    def candidates_named(self, name: str) -> list[str]:
        """Candidates from the last search whose name matches `name`.

        A controller answers with the surname we printed — we write "Captain
        N. Sen (C-1526)", they type "why not Sen". The roster has six Sens and
        only one of them is on the table, so the people already under
        discussion have to be searched before the roster is.
        """
        wanted = name.strip().lower()
        if not wanted:
            return []
        search = self.last_search
        if search is None:
            return []

        found: list[str] = []
        for record in list(search.options) + list(search.excluded):
            get = record.get if isinstance(record, dict) else (
                lambda k, d=None, _r=record: getattr(_r, k, d))
            crew_id = get("crew_id")
            full = (get("name") or "").lower()
            if not crew_id or not full:
                continue
            # "Sen" must match "N. Sen" but not "Senan"; compare whole words,
            # and accept the full string so "N. Sen" works too.
            parts = [p.strip(".,") for p in full.split()]
            if wanted == full or wanted in parts:
                if crew_id not in found:
                    found.append(crew_id)
        return found

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
        name = _name_of(record, crew_id)

        if where == "excluded":
            return self._from_prior(
                f"{name} was excluded: {record.get('reason', 'no reason recorded')}",
                search, cites=record.get("rules", []))

        options = search.options
        top = options[0] if options else None
        if record is top:
            return self._from_prior(
                f"{name} *is* the recommendation — "
                f"₹{record.cost_inr:,}"
                + (f", {record.delay_hours}h delay." if record.delay_hours else ", no delay."),
                search)

        text = (f"{name} is legal, ranked #{getattr(record, 'rank', '?')}: "
                f"₹{record.cost_inr:,}")
        if record.delay_hours:
            text += f" and delays the first departure by {record.delay_hours}h"
        if top is not None:
            text += (f", against ₹{top.cost_inr:,} for "
                     f"{_name_of(top, top.crew_id)}.")
        return self._from_prior(text, search)

    def _answer_next_option(self) -> AdvisorResponse | None:
        """The rest of the ranking, cheapest first.

        The search that produced these already costed and rule-checked every
        one, so "next cheapest option?" is a question about what is on the
        table — answerable with no tool call and no new model reasoning.
        """
        search = self.last_search
        if search is None or len(search.options) < 2:
            return None

        rest = sorted(search.options[1:],
                      key=lambda o: (getattr(o, "cost_inr", 0) or 0))
        lines = []
        for option in rest[:4]:
            crew_id = getattr(option, "crew_id", None)
            if not crew_id:
                continue
            cost = getattr(option, "cost_inr", 0) or 0
            delay = getattr(option, "delay_hours", 0) or 0
            tail = f", {delay:g}h delay" if delay else ", no delay"
            lines.append(f"{_name_of(option, crew_id)} — ₹{cost:,}{tail}")
        if not lines:
            return None

        top = search.options[0]
        head = (f"After {_name_of(top, top.crew_id)} at "
                f"₹{getattr(top, 'cost_inr', 0) or 0:,}, cheapest first:")
        return self._from_prior(head + "\n" + "\n".join(lines), search)

    def _answer_decision(self, crew_id: str) -> AdvisorResponse | None:
        """Record what the controller chose. The desk decides; we advise."""
        found = self.candidate(crew_id)
        if found is None:
            return None
        prior, chosen, where = found

        if where == "excluded":
            # Refuse to book someone the rules engine rejected, and say why.
            return self._from_prior(
                f"I cannot record {_name_of(chosen, crew_id)}: they were "
                f"excluded — {chosen.get('reason', 'no reason recorded')}",
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

    def _from_prior(self, text: str, prior: Exchange | None,
                    cites: list[str] | None = None,
                    awaiting: str | None = None) -> AdvisorResponse:
        """An answer built from a previous turn's evidence.

        The trace is carried over so the verifier still has something to check
        against — a follow-up is not exempt from sourcing just because it
        needed no new tool call.

        `prior` may be None: the very first thing a controller says can still
        be a question we have to hand back, and "which Nair?" needs no earlier
        turn to be a fair thing to ask.
        """
        from agent.schemas import Citation, Intent, Tier

        return AdvisorResponse(
            tier=prior.response.tier if prior else Tier.LOOKUP,
            intent=prior.response.intent if prior else Intent.LOOKUP_CREW,
            entities=prior.response.entities if prior else {},
            answer=prior.response.answer if prior else None,
            narrative=text,
            citations=[Citation(kind="rule", id=r) for r in (cites or [])],
            confidence=Confidence.HIGH,
            trace=prior.response.trace if prior else [],
            awaiting=awaiting,
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

        # 1b. Answering a "which one?" with the id.
        #
        #     `pending_confirmation` above only sees a NEEDS_CONFIRMATION entry
        #     in the trace. The disambiguation raised by `_resolve_name` — the
        #     "Reddy matches 3 crew, which one?" question — runs no tool and so
        #     leaves no trace at all; it marks the response `awaiting` instead.
        #     Without this branch the id was treated as a brand new question:
        #     "what will it cost to choose Reddy?" / "C-3310" answered with a
        #     dossier on C-3310 and dropped the cost question entirely.
        if (prior is not None
                and prior.response.awaiting == "confirmation"
                and ents.crew_ids
                and _is_bare_id(query)):
            chosen = ents.crew_ids[0]
            resumed = prior.query
            for name in prior.entities.names:
                resumed = re.sub(rf"\b{re.escape(name)}\b", chosen, resumed,
                                 flags=re.I)
            if resumed == prior.query:      # the name was not spelled that way
                resumed = f"{prior.query} ({chosen})"
            return self._record(resumed, self._advisor.ask(resumed), ents)

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

            # "Next cheapest option?" names nobody — it asks about the ranking
            # we just produced. Handled before name resolution, which used to
            # read "Next" as a surname and answer "no crew called Next".
            if (target is None and not ents.names
                    and NEXT_OPTION_RE.search(query)):
                if answer := self._answer_next_option():
                    return self._record(query, answer, ents)

            # "why not Sen?" is the same question as "why not C-1526?" — the
            # controller is using the name we printed. Resolve it against the
            # people this search actually put on the table before anything
            # else: the roster has six Sens, and only one is under discussion.
            # Unresolved, this fell through to a roster-wide name lookup and
            # answered a follow-up about one candidate by listing five
            # strangers from other bases.
            if target is None and ents.names:
                for name in ents.names:
                    hits = self.candidates_named(name)
                    if len(hits) == 1:
                        target = hits[0]
                        break
                    # Three Reddys were considered, so the surname is ambiguous
                    # across the pool — but we had just written "Take Captain
                    # D. Reddy (C-3310)". A controller answering that with
                    # "Reddy" means the one we named, not the two we ranked
                    # below it. Only the recommendation gets this; between any
                    # other pair we still ask.
                    if (rec := self.recommended_id()) and rec in hits:
                        target = rec
                        break

            if target and (WHY_NOT_RE.search(query) or WHAT_ABOUT_RE.search(query)):
                if answer := self._answer_about(target):
                    return self._record(query, answer)

            if (DECIDE_RE.search(query) and target
                    and not QUESTION_RE.search(query)
                    and not COST_RE.search(query)):
                if answer := self._answer_decision(target):
                    return self._record(query, answer)

            # Asking the price of a candidate is a question about them, which
            # the previous turn already costed — not a new search, and above
            # all not a booking.
            if target and COST_RE.search(query):
                if answer := self._answer_about(target):
                    return self._record(query, answer)

        # 5. A person named in words rather than by id. The system writes
        #    "Captain A. Nair (C-1042)", so a controller writes "Nair" back —
        #    and if that is not resolved the query runs with no crew filter at
        #    all and answers with the roster.
        if ents.names and not ents.crew_ids:
            named = self._resolve_name(ents, prior)
            if named is not None:
                if isinstance(named, str):
                    query_for_agent = self._name_to_id(query, ents, named)
                    ents.crew_ids = [named]
                    return self._record(
                        query, self._advisor.ask(query_for_agent), ents)
                return self._record(query, named, ents)

        # 6. A new question, with whatever this turn left implicit filled in.
        query_for_agent = query
        if prior is not None and (WHAT_ABOUT_RE.search(query)
                                  or ANAPHORA_RE.search(query)
                                  or not ents.to_dict()):
            _, ents = self._inherit(query, ents)
            query_for_agent = self._rewrite(query, ents)

        return self._record(query, self._advisor.ask(query_for_agent), ents)

    def _resolve_name(self, ents: Entities, prior: Any) -> Any:
        """A crew id, a question back to the controller, or None to carry on.

        Three outcomes and no fourth. Exactly one match resolves. Several
        matches ask which — every surname in this dataset is shared, and
        "A. Nair" alone is a Captain and a Cabin Crew member at the same base,
        so picking one would dispatch the wrong human being (DECISIONS.md
        #22). No match at all means the word was never a name — "Sep" is not
        a person — and the question proceeds untouched.

        Context wins first. Right after discussing Captain A. Nair (C-1042),
        "is Nair available?" means that one, not the other six.
        """
        from agent.tools import crew_named

        for candidate in ents.names:
            try:
                matches = crew_named(self._advisor.port, candidate)
            except Exception:
                return None
            if not matches:
                continue

            if prior is not None and len(matches) > 1:
                # Who is "in context" is both who the controller named and who
                # we offered back. Narrowing on the query's ids alone missed
                # every candidate from our own answer — the usual case, since
                # a controller replies with a name we printed, not one they
                # typed.
                known = set(prior.entities.crew_ids) | self.candidate_ids()
                if narrowed := [m for m in matches if m["crew_id"] in known]:
                    matches = narrowed
                # Still several, and one of them is the candidate we just
                # recommended by name: that is the one they mean. "What will it
                # cost to choose Reddy?" straight after "Take Captain D. Reddy
                # (C-3310)" is not an ambiguous question.
                if len(matches) > 1 and (rec := self.recommended_id()):
                    if pick := [m for m in matches if m["crew_id"] == rec]:
                        matches = pick
            if ents.roles:
                if narrowed := [m for m in matches if m["rank"] == ents.roles[0]]:
                    matches = narrowed
            if ents.stations:
                if narrowed := [m for m in matches if m["base"] == ents.stations[0]]:
                    matches = narrowed

            if len(matches) == 1:
                return matches[0]["crew_id"]

            listed = "; ".join(
                explainer.who(m["crew_id"], m["name"], m["rank"]) + f" at {m['base']}"
                for m in matches[:8])
            more = "" if len(matches) <= 8 else f" (and {len(matches) - 8} others)"
            return self._from_prior(
                f"{candidate} matches {len(matches)} crew: {listed}{more}. "
                f"Which one? Give me the id and I will run it — I will not "
                f"guess, because they are different people.",
                prior, awaiting="confirmation")

        # Every candidate drew a blank. Most are not names at all — "Sep",
        # "Available" — and those must not derail the question. But a query
        # whose *only* subject was an unrecognised name would otherwise run
        # with no crew filter and answer with the roster, which is the one
        # outcome worse than saying "I don't know who that is".
        if not any((ents.pairing_ids, ents.flight_ids, ents.flight_nos,
                    ents.rule_ids, ents.aircraft, ents.stations, ents.roles)):
            unknown = self._closest_names(ents.names)
            if unknown:
                return self._from_prior(unknown, prior, awaiting="detail")
        return None

    def _closest_names(self, candidates: list[str]) -> str:
        """"I don't know who that is", with the nearest surnames we do know.

        Only for a word that plausibly *was* meant as a name. Returning the
        whole roster instead would be a non-answer dressed as one.
        """
        import difflib

        try:
            crew = self._advisor.port.lookup("crew")
        except Exception:
            return ""
        surnames = sorted({str(c.get("name") or "").split()[-1] for c in crew if c.get("name")})

        for candidate in candidates:
            near = difflib.get_close_matches(candidate, surnames, n=3, cutoff=0.6)
            if near:
                return (f"No crew called {candidate}. The roster has "
                        f"{', '.join(near)} — did you mean one of those? "
                        f"Or give me the id.")
            # Nothing close either. Still say so: the alternative is running
            # the query with no crew filter and answering a question about one
            # person with all 150 of them.
            return (f"No crew called {candidate}, and nothing on the roster is "
                    f"close to it. Crew ids look like C-1042 — give me one, or "
                    f"tell me the rank and base and I will list who fits.")
        return ""

    @staticmethod
    def _name_to_id(query: str, ents: Entities, crew_id: str) -> str:
        """Hand the advisor the id, keeping the controller's own wording."""
        rewritten = query
        for candidate in ents.names:
            rewritten = rewritten.replace(candidate, f"{candidate} ({crew_id})")
        return rewritten if crew_id in rewritten else f"{query} ({crew_id})"

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
