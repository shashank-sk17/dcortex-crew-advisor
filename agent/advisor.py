"""The advisor loop.

    ROUTER -> PLANNER -> TOOL LOOP -> VERIFIER -> EXPLAINER

One agent with tools, not a multi-agent system. All the hard reasoning is
deterministic Python in `core/`; a multi-agent decomposition would have models
conferring about work that is already exact, paying serial round-trips for no
added correctness on a latency-critical desk (DECISIONS.md #13).

The loop never lets the model compute. It chooses tools, the tools compute,
the verifier proves the prose only repeats what the tools said.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import Any, Iterator

from agent import config, explainer, verifier
from agent.entities import stated_ranks
from agent.llm import LLM, StreamEvent, ToolCall, default_llm
from agent.prompts import system_prompt
from agent.router import Route, route
from agent.schemas import (
    AdvisorResponse,
    BlastRadius,
    Confidence,
    ConsequenceAnswer,
    FunnelStage,
    Intent,
    LookupAnswer,
    Option,
    ReplacementAnswer,
    RuleVerdict,
    Tier,
    TraceEntry,
    Verdict,
)
from agent.tools import TOOL_SCHEMAS, PlaceholderToolPort, ToolPort, dispatch, schemas_for_port


@dataclass(slots=True)
class AdvisorConfig:
    max_iterations: int = config.MAX_TOOL_ITERATIONS
    verify: bool = True
    polish: bool = True
    max_verify_retries: int = 1


# A tool can end a turn by asking the controller something. These are not
# failures to route around — they are questions only a human can settle.
CLARIFYING = ("AMBIGUOUS_QUERY", "NEEDS_CONFIRMATION")


@dataclass(slots=True)
class Turn:
    """Everything that happened while answering one question."""

    query: str
    route: Route | None = None
    trace: list[TraceEntry] = field(default_factory=list)
    iterations: int = 0
    verification: verifier.VerificationResult | None = None
    notes: list[str] = field(default_factory=list)
    seen_calls: set[str] = field(default_factory=set)
    repeats: int = 0
    awaiting_controller: bool = False


# --------------------------------------------------------------------------
# Planning: which tools a given intent needs
# --------------------------------------------------------------------------

_INTENT_TOOLS: dict[Intent, tuple[str, ...]] = {
    Intent.LOOKUP_ROSTER: ("lookup",),
    Intent.LOOKUP_RESERVE: ("lookup",),
    Intent.LOOKUP_CREW: ("lookup",),
    Intent.LOOKUP_FLIGHT: ("lookup",),
    Intent.LOOKUP_CERT: ("lookup",),
    Intent.LOOKUP_DUTY_CLOCK: ("duty_clock",),
    Intent.EXPLAIN_RULE: ("explain_rule",),
    Intent.CHECK_LEGALITY: ("check_legality", "explain_rule"),
    Intent.FIND_REPLACEMENT: ("find_options", "check_legality"),
    Intent.IMPACT_OF_EVENT: ("ripple", "lookup"),
    Intent.RANK_OPTIONS: ("find_options", "ripple", "check_legality"),
    Intent.SIMULATE_WHATIF: ("simulate", "ripple", "find_options"),
    Intent.JOINT_PLAN: ("joint_plan", "find_options"),
    Intent.RESOLVE_ILLEGAL: ("check_legality", "find_options", "ripple"),
}


def tools_for(intent: Intent, port: Any = None) -> list[dict[str, Any]]:
    """Narrow the toolset to what this intent can plausibly need.

    A tier-1 lookup does not get `joint_plan` in its schema list. Fewer, more
    relevant tools measurably improves selection and cuts prompt size.
    """
    schemas = schemas_for_port(port) if port is not None else TOOL_SCHEMAS
    allowed = set(_INTENT_TOOLS.get(intent, ()))
    narrowed = [t for t in schemas if t["name"] in allowed]
    return narrowed or schemas


MISSING_FOR_INTENT: dict[Intent, str] = {
    Intent.CHECK_LEGALITY: "a crew member and the pairing or flight to check them against",
    Intent.FIND_REPLACEMENT: "who is unavailable, or which pairing or flight needs cover",
    Intent.RANK_OPTIONS: "which pairing or flight needs cover",
    Intent.IMPACT_OF_EVENT: "who or what is disrupted",
    Intent.JOINT_PLAN: "at least two pairings or crew members",
    Intent.SIMULATE_WHATIF: "what to change, and which pairing or flight it affects",
    Intent.RESOLVE_ILLEGAL: "the crew member and date whose assignment is in question",
    Intent.EXPLAIN_RULE: "a rule id, e.g. RULE-DUTY-02",
    Intent.LOOKUP_DUTY_CLOCK: "a crew id, e.g. C-1042",
}


def explain_no_tools(route: Route) -> str:
    """Why nothing ran — never an empty answer.

    A narrow seeding guard used to end the query in silence: no tool fired,
    the answer object stayed empty, and the controller read "No data was
    returned for this question." That is the one outcome this system must
    never produce, because it is indistinguishable from "nothing is wrong".

    So an empty trace reports what was understood, what is missing, and what
    would unblock it.
    """
    ents = route.entities.to_dict()
    lines = [f"I read this as {str(route.intent).replace('_', ' ').lower()} "
             f"but could not run it."]

    if ents:
        found = "; ".join(f"{k.replace('_', ' ')}: {', '.join(map(str, v))}"
                          for k, v in ents.items())
        lines.append(f"\nI did pick out — {found}")
    else:
        lines.append("\nI could not pick out a single id from that. Crew look "
                     "like C-1042, pairings like P-2291, flights like DX412.")

    if needed := MISSING_FOR_INTENT.get(route.intent):
        lines.append(f"\nTo answer it I need {needed}.")

    lines.append("\nNothing was checked, so this is not evidence that the "
                 "operation is clean.")
    return "\n".join(lines)


def _flight_filters(ents: Any) -> dict[str, Any]:
    """Build a flight filter, honouring a destination when one is named.

    "BLR->BOM" names two stations. Filtering on the first alone returns every
    departure from BLR and silently drops half the question — which is exactly
    what happened to "Captain of BLR->BOM not available".
    """
    filters: dict[str, Any] = {}
    if ents.stations:
        filters["dep_station"] = ents.stations[0]
    if len(ents.stations) > 1:
        filters["arr_station"] = ents.stations[1]
    if ents.primary_date:
        filters["date"] = ents.primary_date
    if ents.flight_nos:
        filters["flight_no"] = ents.flight_nos[0]
    return filters


def seed_calls(route: Route) -> list[ToolCall]:
    """First tool calls implied by the entities, before the model is consulted.

    The router already extracted the ids deterministically, so for the common
    shapes we know the opening move. This saves a round-trip and guarantees the
    model sees real data before it says anything.
    """
    ents = route.entities
    calls: list[ToolCall] = []

    def add(name: str, **args: Any) -> None:
        calls.append(ToolCall(id=f"seed-{len(calls)}", name=name, args=args))

    match route.intent:
        case Intent.EXPLAIN_RULE if ents.rule_ids:
            for rule_id in ents.rule_ids:
                add("explain_rule", rule_id=rule_id)

        case Intent.LOOKUP_DUTY_CLOCK if ents.primary_crew:
            add("duty_clock", crew_id=ents.primary_crew, date=ents.primary_date)

        case Intent.LOOKUP_RESERVE:
            filters = {"base": ents.stations[0]} if ents.stations else {}
            add("lookup", entity="reserves", filters=filters)

        case Intent.LOOKUP_FLIGHT:
            add("lookup", entity="flights", filters=_flight_filters(ents))

        case Intent.CHECK_LEGALITY if ents.primary_crew and ents.primary_pairing:
            add("check_legality",
                crew_id=ents.primary_crew, pairing_id=ents.primary_pairing)

        case Intent.CHECK_LEGALITY if ents.primary_crew and (
                ents.flight_ids or ents.flight_nos):
            # "Move C-2087 onto DX412" names a leg, not a pairing. Crew are
            # assigned to whole pairings, so the leg has to be resolved first.
            add("check_legality", crew_id=ents.primary_crew,
                flight_id=ents.flight_ids[0] if ents.flight_ids else None,
                flight_no=ents.flight_nos[0] if ents.flight_nos else None,
                date=ents.primary_date)

        case (Intent.FIND_REPLACEMENT | Intent.RANK_OPTIONS) if ents.primary_pairing:
            add("find_options",
                pairing_id=ents.primary_pairing,
                role=ents.roles[0] if ents.roles else "Captain")

        case (Intent.FIND_REPLACEMENT | Intent.RANK_OPTIONS) if ents.primary_crew:
            # "C-1042 is sick" names a person, not a trip. The roster knows
            # which pairing they are on and in what role; asking the model to
            # supply either is asking it to guess.
            add("find_options", crew_id=ents.primary_crew)
            add("ripple", event={"type": "SICK_CREW", "crew_id": ents.primary_crew})

        case (Intent.FIND_REPLACEMENT | Intent.RANK_OPTIONS) if ents.stations:
            # A disruption named by route rather than pairing — "captain of
            # BLR->BOM is out". Identify the leg first; the pairing it belongs
            # to is what `find_options` actually needs.
            add("lookup", entity="flights", filters=_flight_filters(ents))

        case Intent.IMPACT_OF_EVENT if ents.primary_crew or ents.primary_pairing:
            add("ripple", event={
                "type": "SICK_CREW",
                "crew_id": ents.primary_crew,
                "pairing_id": ents.primary_pairing,
                "reported_utc": ents.primary_date,
            })

        case Intent.JOINT_PLAN if len(ents.pairing_ids) >= 2:
            add("joint_plan", events=[
                {"type": "SICK_CREW", "pairing_id": pid} for pid in ents.pairing_ids
            ])

    return calls


# --------------------------------------------------------------------------
# Assembling the answer object
# --------------------------------------------------------------------------


def followup_calls(route: Route, trace: list[TraceEntry]) -> list[ToolCall]:
    """Calls derivable from what the seeds already returned.

    A disruption named by route — "captain of BLR->BOM is out" — needs a leg
    identified before cover can be found. The seed does that lookup, and the
    flight id is then sitting in the trace; asking the model to carry it across
    is asking it to do bookkeeping it is bad at. Left to itself, qwen3:8b
    passed the literal string "BLR->BOM" as both flight_id and pairing_id.

    So the deterministic layer does the hop it can see, and the model is left
    with the part that actually needs judgement.
    """
    if route.intent not in (Intent.FIND_REPLACEMENT, Intent.RANK_OPTIONS):
        return []
    if any(e.tool == "find_options" for e in trace):
        return []

    flights = [
        row
        for entry in trace
        if entry.tool == "lookup" and isinstance(entry.result, list)
        for row in entry.result
        if isinstance(row, dict) and "flight_id" in row
    ]
    if not flights:
        return []

    role = route.entities.roles[0] if route.entities.roles else "Captain"
    return [ToolCall(
        id="followup-0",
        name="find_options",
        args={"flight_id": flights[0]["flight_id"], "role": role},
    )]


def _coerce(cls: Any, rows: Any) -> list[Any]:
    """Turn raw tool output into the typed objects the renderer expects.

    Tools return plain JSON — from fixtures, from Postgres, and eventually
    over HTTP from `core/`. Passing dicts straight through works right up
    until something reads `stage.count` and gets an AttributeError, so the
    conversion belongs here, at the one boundary where the answer object is
    assembled. Unknown keys are dropped rather than raising: a backend that
    adds a field must not break the UI.
    """
    fields = {f.name for f in dataclass_fields(cls)}
    out = []
    for row in rows or []:
        if isinstance(row, cls):
            out.append(row)
        elif isinstance(row, dict):
            kwargs = {k: v for k, v in row.items() if k in fields}
            if cls is RuleVerdict and "status" in kwargs:
                # JSON gives us the string; rebuild the enum so identity
                # comparisons elsewhere cannot silently misread it.
                kwargs["status"] = Verdict(str(kwargs["status"]))
            out.append(cls(**kwargs))
    return out


def build_answer(route: Route, trace: list[TraceEntry]) -> Any:
    """Fold tool results into the typed body for this tier.

    Structured object first; prose is rendered from it (DECISIONS.md #4).
    """
    results = {e.tool: e.result for e in trace if e.result is not None}

    if route.tier is Tier.LOOKUP:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for entry in trace:
            if entry.result is None:
                continue
            found = entry.result if isinstance(entry.result, list) else [entry.result]
            for row in found:
                if not isinstance(row, dict):
                    continue
                # Deduplicate across calls. A seeded lookup and the model's own
                # near-identical one both return the same rows; concatenating
                # them doubles the count, and that doubled figure matches no
                # tool output, so the verifier rightly rejects the answer.
                key = repr(sorted(row.items(), key=str))
                if key not in seen:
                    seen.add(key)
                    rows.append(row)
        return LookupAnswer(rows=rows)

    if route.tier is Tier.REPLACEMENT:
        found = results.get("find_options") or {}
        rippled = results.get("ripple") or {}
        # A legality verdict is a complete answer on its own. Reading only
        # find_options and ripple discarded it silently, so "does any rule
        # breach?" computed the right verdict and then reported nothing.
        checked = results.get("check_legality") or {}
        rec = _coerce(Option, [found["recommended"]]) if found.get("recommended") else []
        return ReplacementAnswer(
            subject=checked.get("crew_id"),
            legal=checked.get("legal"),
            verdicts=_coerce(RuleVerdict, checked.get("verdicts")),
            recommended=rec[0] if rec else None,
            cancellation_multiple=found.get("cancellation_multiple", 0),
            next_tier_cost_inr=found.get("next_tier_cost_inr", 0),
            next_tier_premium_inr=found.get("next_tier_premium_inr", 0),
            equal_cost_alternatives=found.get("equal_cost_alternatives", 0),
            uncovered_flights=rippled.get("uncovered_flights", []),
            at_risk_flights=rippled.get("at_risk_flights", []),
            passengers_affected=rippled.get("passengers", 0),
            funnel=_coerce(FunnelStage, found.get("funnel")),
            options=_coerce(Option, found.get("options")),
            near_misses=_coerce(Option, found.get("near_misses")),
            excluded=found.get("excluded", []),
        )

    found = results.get("find_options") or {}
    blast = (results.get("ripple") or {}).get("blast_radius")
    return ConsequenceAnswer(
        options=_coerce(Option, found.get("options")),
        blast_radius=(_coerce(BlastRadius, [blast]) or [None])[0],
        world_diff=results.get("simulate"),
        joint_plan=results.get("joint_plan"),
    )


# --------------------------------------------------------------------------
# Advisor
# --------------------------------------------------------------------------


class Advisor:
    """Answers one question at a time. Stateless between calls.

    >>> a = Advisor()
    >>> r = a.ask("What does RULE-DUTY-02 say?")
    >>> r.intent
    <Intent.EXPLAIN_RULE: 'EXPLAIN_RULE'>
    >>> r.trace[0].tool
    'explain_rule'
    """

    def __init__(
        self,
        port: ToolPort | None = None,
        llm: LLM | None = None,
        cfg: AdvisorConfig | None = None,
    ) -> None:
        self.port = port or PlaceholderToolPort()
        self.llm = llm or default_llm()
        self.cfg = cfg or AdvisorConfig()

    # -- the loop ---------------------------------------------------------

    @staticmethod
    def _signature(call: ToolCall) -> str:
        return f"{call.name}:{sorted((call.args or {}).items())!r}"

    def _run_tools(self, calls: list[ToolCall], turn: Turn) -> None:
        """Execute calls, skipping any already made this turn.

        Small local models loop: llama3.1:8b will re-request an identical call
        every iteration until the cap. The results are deterministic, so a
        repeat adds nothing but latency and a duplicated trace row.
        """
        for call in calls:
            signature = self._signature(call)
            if signature in turn.seen_calls:
                turn.repeats += 1
                continue
            turn.seen_calls.add(signature)

            entry = dispatch(self.port, call.name, call.args)
            turn.trace.append(entry)
            if entry.error:
                turn.notes.append(f"{entry.tool}: {entry.error}")
                if entry.error.startswith(CLARIFYING):
                    # "DX412 operates on three dates — which do you mean?" is a
                    # question for the controller. Left to continue, the model
                    # answered it itself: it checked all three dates and then
                    # narrated whichever it preferred, so the same question
                    # produced different answers on different runs. Choosing
                    # among them is the desk's call, not ours.
                    turn.awaiting_controller = True
                    return

    def _tool_loop(self, turn: Turn) -> None:
        """Seed from entities, then let the model request more until it stops."""
        assert turn.route is not None

        if seeds := seed_calls(turn.route):
            self._run_tools(seeds, turn)
            if turn.awaiting_controller:
                return
            if followups := followup_calls(turn.route, turn.trace):
                self._run_tools(followups, turn)
            if turn.awaiting_controller:
                return

        tools = tools_for(turn.route.intent, self.port)
        messages: list[dict[str, Any]] = [{"role": "user", "content": turn.query}]

        while turn.iterations < self.cfg.max_iterations:
            turn.iterations += 1
            response = self.llm.complete(
                system=system_prompt(turn.route.intent),
                messages=messages,
                tools=tools,
                model=config.ADVISOR_MODEL,
            )
            if not response.wants_tools:
                break
            before = len(turn.trace)
            self._run_tools(response.tool_calls, turn)
            if turn.awaiting_controller:
                return
            if len(turn.trace) == before:
                # Every requested call was a repeat: the model is looping and
                # has no new evidence to gather. Stop rather than burn the cap.
                break
            # Anthropic requires an id on every tool_use and a matching
            # tool_use_id on its result. The OpenAI-compatible backends
            # flatten these to text and ignore the ids, so carrying them
            # costs nothing there and is mandatory here.
            executed = turn.trace[-len(response.tool_calls):]
            messages.append({
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.args}
                    for c in response.tool_calls
                ],
            })
            messages.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": c.id,
                     "content": str(e.result if e.result is not None else e.error),
                     **({"is_error": True} if e.error else {})}
                    for c, e in zip(response.tool_calls, executed)
                ],
            })

    def _confidence(self, turn: Turn) -> tuple[Confidence, list[str]]:
        """Never claim high confidence on top of a failed tool."""
        unknowns = [n for n in turn.notes]
        errored = any(e.error for e in turn.trace)

        if turn.awaiting_controller:
            # A question for the controller is a complete, confident answer.
            return Confidence.HIGH, []

        if not turn.trace:
            return Confidence.LOW, unknowns + ["no tool produced any data"]
        if errored:
            return Confidence.LOW, unknowns
        if turn.route and turn.route.confidence is Confidence.LOW:
            return Confidence.MEDIUM, unknowns
        return Confidence.HIGH, unknowns

    def rank_mismatch(self, query: str) -> str | None:
        """A rank the query asserts that the roster contradicts.

        dCortex's own problem statement says "FO C-2087" and their dataset
        README flags it as an erratum — C-2087 is a Captain. A controller
        typing that has either misremembered the seat or means a different
        person, and both change the answer. Accepting it silently is the
        failure; the roster knows, so it should say.
        """
        for crew_id, claimed in stated_ranks(query):
            try:
                rows = self.port.lookup("crew", {"crew_id": crew_id})
            except Exception:
                continue
            if not rows:
                continue
            actual = rows[0].get("rank")
            if actual and actual != claimed:
                return (f"{crew_id} is a {actual}, not a {claimed}. "
                        f"Did you mean a different crew member, or shall I "
                        f"proceed with {crew_id} as {actual}?")
        return None

    def ask(self, query: str, llm: LLM | None = None) -> AdvisorResponse:
        """Route, gather evidence, verify, explain."""
        turn = Turn(query=query)
        turn.route = route(query, llm or self.llm)

        # Before anything runs: does the query assert something about a person
        # that the roster contradicts? Answering the wrong seat confidently is
        # worse than asking.
        if mismatch := self.rank_mismatch(query):
            turn.trace.append(TraceEntry(
                tool="roster_check", args={"query": query},
                error=f"NEEDS_CONFIRMATION: {mismatch}"))
            turn.awaiting_controller = True
        else:
            self._tool_loop(turn)

        confidence, unknowns = self._confidence(turn)
        response = AdvisorResponse(
            tier=turn.route.tier,
            intent=turn.route.intent,
            entities=turn.route.entities.to_dict(),
            answer=build_answer(turn.route, turn.trace),
            confidence=confidence,
            unknowns=unknowns,
            trace=turn.trace,
        )

        if turn.awaiting_controller:
            asked = next(e for e in turn.trace
                         if e.error and e.error.startswith(CLARIFYING))
            code, _, detail = asked.error.partition(":")
            response.narrative = detail.strip()
            response.awaiting = ("confirmation" if code == "NEEDS_CONFIRMATION"
                                 else "detail")
            response.confidence = Confidence.HIGH
            return response

        if not turn.trace:
            # Nothing ran at all. Say why rather than returning silence.
            response.narrative = explain_no_tools(turn.route)
            response.confidence = Confidence.LOW
            return response

        narrative = explainer.render(response)
        if self.cfg.polish:
            narrative = explainer.polish(response, self.llm)

        if self.cfg.verify:
            result = verifier.verify(narrative, turn.trace)
            turn.verification = result
            if not result.ok:
                # The gate rejected the draft. Fall back to the deterministic
                # renderer, which can only restate tool output, and say so
                # rather than shipping an unsourced claim.
                narrative = explainer.render(response)
                # Only ever lower confidence here. A rejected draft is bad
                # news; it must not promote an answer that was already LOW
                # because its tools failed.
                if response.confidence is Confidence.HIGH:
                    response.confidence = Confidence.MEDIUM
                # Say what happened, not just that something failed. The answer
                # on screen is the verified one; it is the model's discarded
                # draft that was unsupported, and a bare "UNVERIFIED" makes the
                # good answer look like the suspect one.
                if bad := ", ".join(c.value for c in result.unsupported):
                    response.unknowns.append(
                        f"The model's draft claimed {bad}, which no tool output "
                        f"supports. That draft was discarded — what is shown "
                        f"above is rendered directly from the tool results."
                    )
                else:
                    # No unsupported claims means the draft failed for another
                    # reason — almost always that no tool ran at all. Saying
                    # "claimed , which no tool supports" is worse than useless.
                    response.unknowns.append(result.summary())

        response.narrative = narrative
        response.citations = explainer.collect_citations(response)
        return response

    # -- streaming --------------------------------------------------------

    def stream(self, query: str) -> Iterator[StreamEvent]:
        """SSE events matching docs/API_CONTRACT.md.

        Tool calls are emitted as they happen so the console can render the
        reasoning trace live — a controller watching the work is a controller
        who trusts the result.
        """
        turn = Turn(query=query)
        turn.route = route(query, self.llm)
        yield StreamEvent("tool_call", {"router": turn.route.to_dict()})

        for call in seed_calls(turn.route):
            yield StreamEvent("tool_call", {"tool": call.name, "args": call.args})
            entry = dispatch(self.port, call.name, call.args)
            turn.trace.append(entry)
            yield StreamEvent("tool_result", {
                "tool": entry.tool, "ms": entry.ms, "error": entry.error,
            })

        response = AdvisorResponse(
            tier=turn.route.tier,
            intent=turn.route.intent,
            entities=turn.route.entities.to_dict(),
            answer=build_answer(turn.route, turn.trace),
            trace=turn.trace,
        )
        response.narrative = explainer.render(response)
        response.citations = explainer.collect_citations(response)

        for line in response.narrative.splitlines(keepends=True):
            yield StreamEvent("token", {"text": line})
        yield StreamEvent("done", {"answer": response.to_dict()})
