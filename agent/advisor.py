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
    Tier,
    TraceEntry,
)
from agent.tools import TOOL_SCHEMAS, PlaceholderToolPort, ToolPort, dispatch, schemas_for_port


@dataclass(slots=True)
class AdvisorConfig:
    max_iterations: int = config.MAX_TOOL_ITERATIONS
    verify: bool = True
    polish: bool = True
    max_verify_retries: int = 1


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

        case (Intent.FIND_REPLACEMENT | Intent.RANK_OPTIONS) if ents.primary_pairing:
            add("find_options",
                pairing_id=ents.primary_pairing,
                role=ents.roles[0] if ents.roles else "Captain")

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
            out.append(cls(**{k: v for k, v in row.items() if k in fields}))
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
        return ReplacementAnswer(
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

    def _tool_loop(self, turn: Turn) -> None:
        """Seed from entities, then let the model request more until it stops."""
        assert turn.route is not None

        if seeds := seed_calls(turn.route):
            self._run_tools(seeds, turn)

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
            if len(turn.trace) == before:
                # Every requested call was a repeat: the model is looping and
                # has no new evidence to gather. Stop rather than burn the cap.
                break
            messages.append({
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": c.name, "input": c.args}
                    for c in response.tool_calls
                ],
            })
            messages.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "content": str(e.result or e.error)}
                    for e in turn.trace[-len(response.tool_calls):]
                ],
            })

    def _confidence(self, turn: Turn) -> tuple[Confidence, list[str]]:
        """Never claim high confidence on top of a failed tool."""
        unknowns = [n for n in turn.notes]
        errored = any(e.error for e in turn.trace)

        if not turn.trace:
            return Confidence.LOW, unknowns + ["no tool produced any data"]
        if errored:
            return Confidence.LOW, unknowns
        if turn.route and turn.route.confidence is Confidence.LOW:
            return Confidence.MEDIUM, unknowns
        return Confidence.HIGH, unknowns

    def ask(self, query: str, llm: LLM | None = None) -> AdvisorResponse:
        """Route, gather evidence, verify, explain."""
        turn = Turn(query=query)
        turn.route = route(query, llm or self.llm)

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
