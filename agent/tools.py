"""The tool boundary — where the language model stops and Python starts.

This is the trust boundary. Everything below it is deterministic and unit
tested; the model above it may only *choose* tools and *narrate* what they
return. It never computes a duty hour or a cost itself.

Tools are coarse and semantically meaningful rather than micro-CRUD, so a
tier-2 question is three calls rather than thirty.

`ToolPort` is the seam to `core/`. Two implementations are expected:

    PlaceholderToolPort   deterministic canned rows — available today
    CoreToolPort          delegates to core/ once Kashifa's World lands

Both must satisfy `evals/contract_test.py`, which is what makes the swap a
no-op (DECISIONS.md #3).
"""

from __future__ import annotations

import time
from typing import Any, Protocol, runtime_checkable

from agent.schemas import TraceEntry

# --------------------------------------------------------------------------
# Tool schemas — vendor-neutral JSON Schema, passed straight to the model
# --------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "lookup",
        "description": (
            "Retrieve rows from the operational dataset. The tier-1 workhorse: "
            "crew, flights, pairings, reserves, certifications, risk signals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "enum": [
                        "crew", "flights", "pairings", "reserves",
                        "certifications", "risk_signals", "costs",
                    ],
                },
                "filters": {
                    "type": "object",
                    "description": (
                        "Field equality filters, e.g. {'base': 'BLR', "
                        "'rank': 'Captain'}. Dates are ISO-8601."
                    ),
                },
            },
            "required": ["entity"],
        },
    },
    {
        "name": "duty_clock",
        "description": (
            "A crew member's accrued duty and block hours with headroom under "
            "RULE-DUTY-02 and RULE-FLT-03. Windows are calendar-day based."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "crew_id": {"type": "string", "pattern": "^C-[0-9]{4}$"},
                "date": {"type": "string", "description": "ISO date; defaults to snapshot"},
            },
            "required": ["crew_id"],
        },
    },
    {
        "name": "check_legality",
        "description": (
            "Evaluate all 7 rules for assigning a crew member to a pairing. "
            "Returns a verdict per rule with the numbers, never a bare boolean. "
            "This is the only legal authority in the system."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "crew_id": {"type": "string", "pattern": "^C-[0-9]{4}$"},
                "pairing_id": {"type": "string", "pattern": "^P-[0-9]{4}$"},
                "delay_h": {
                    "type": "number",
                    "description": "Hypothetical departure delay, for near-miss checks",
                },
            },
            "required": ["crew_id", "pairing_id"],
        },
    },
    {
        "name": "find_options",
        "description": (
            "Enumerate and rank every way to cover an uncrewed pairing: reserve "
            "callout, day-off callout, deadhead positioning, delay, cancel. "
            "Returns the candidate funnel with a reason for every drop."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pairing_id": {"type": "string", "pattern": "^P-[0-9]{4}$"},
                "role": {
                    "type": "string",
                    "enum": ["Captain", "First Officer", "Senior Cabin Crew", "Cabin Crew"],
                },
                "callout_utc": {"type": "string", "description": "ISO-8601 UTC"},
            },
            "required": ["pairing_id", "role"],
        },
    },
    {
        "name": "ripple",
        "description": (
            "Blast radius of a disruption: directly uncovered flights, orphaned "
            "downstream pairing days, passengers affected, reserve pool "
            "depletion, aircraft rotation knock-on."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event": {
                    "type": "object",
                    "description": (
                        "e.g. {'type':'SICK_CREW','crew_id':'C-1042',"
                        "'pairing_id':'P-2291','reported_utc':'...'}"
                    ),
                }
            },
            "required": ["event"],
        },
    },
    {
        "name": "simulate",
        "description": (
            "Fork the world, apply a perturbation, re-evaluate, and return the "
            "diff. Handles SICK_CREW, STATION_CLOSURE, TECH_DELAY, CERT_LAPSE."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"event": {"type": "object"}},
            "required": ["event"],
        },
    },
    {
        "name": "joint_plan",
        "description": (
            "Cost-minimal assignment across several simultaneous disruptions, "
            "under the constraint that one crew member cannot cover two "
            "pairings. Note that ties are common and all are equally correct."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "events": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["events"],
        },
    },
    {
        "name": "explain_rule",
        "description": "The text, parameters and plain-English gloss of one rule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string", "pattern": "^RULE-[A-Z]{3,4}-[0-9]{2}$"}
            },
            "required": ["rule_id"],
        },
    },
]

TOOL_NAMES: frozenset[str] = frozenset(t["name"] for t in TOOL_SCHEMAS)


# --------------------------------------------------------------------------
# The seam to core/
# --------------------------------------------------------------------------


@runtime_checkable
class ToolPort(Protocol):
    """What `core/` must provide. Mirrors TOOL_SCHEMAS one-for-one."""

    def lookup(self, entity: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...
    def duty_clock(self, crew_id: str, date: str | None = None) -> dict[str, Any]: ...
    def check_legality(self, crew_id: str, pairing_id: str, delay_h: float = 0.0) -> dict[str, Any]: ...
    def find_options(self, pairing_id: str, role: str, callout_utc: str | None = None) -> dict[str, Any]: ...
    def ripple(self, event: dict[str, Any]) -> dict[str, Any]: ...
    def simulate(self, event: dict[str, Any]) -> dict[str, Any]: ...
    def joint_plan(self, events: list[dict[str, Any]]) -> dict[str, Any]: ...
    def explain_rule(self, rule_id: str) -> dict[str, Any]: ...


class ToolError(RuntimeError):
    """A tool failed in a way the model should see and route around."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PlaceholderToolPort:
    """Stands in for `core/` until the real engine lands.

    Reads what it can straight from the vendored dataset so tier-1 shapes are
    honest; anything requiring the legality engine raises `ToolError` rather
    than inventing an answer. Fabricating a plausible duty hour here would be
    exactly the failure this architecture exists to prevent.
    """

    _NOT_YET = "core/ is not implemented yet — see issues #1-#12"

    def __init__(self, data_dir: Any = None) -> None:
        from agent import config

        self.data_dir = data_dir or config.DATA_DIR
        self._cache: dict[str, Any] = {}

    def _load(self, name: str) -> Any:
        if name not in self._cache:
            import json

            path = self.data_dir / f"{name}.json"
            if not path.exists():
                raise ToolError("INTERNAL", f"dataset file missing: {path.name}")
            self._cache[name] = json.loads(path.read_text(encoding="utf-8"))
        return self._cache[name]

    # -- implemented against raw data -------------------------------------

    def lookup(self, entity: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        source = {
            "crew": "crew",
            "flights": "flights",
            "reserves": "reserve_pool",
            "certifications": "certifications",
            "risk_signals": "risk_signals",
            "costs": "costs",
            "pairings": "rosters",
        }.get(entity)
        if source is None:
            raise ToolError("UNRESOLVED_ENTITY", f"unknown entity {entity!r}")

        rows = self._load(source)
        if entity == "pairings":
            rows = rows["pairings"]
        if isinstance(rows, dict):
            rows = [rows]

        for key, want in (filters or {}).items():
            rows = [r for r in rows if r.get(key) == want]
        return rows

    def explain_rule(self, rule_id: str) -> dict[str, Any]:
        rules = self._load("rules")["rules"]
        for rule in rules:
            if rule["rule_id"] == rule_id:
                return rule
        raise ToolError("UNRESOLVED_ENTITY", f"no rule {rule_id!r}")

    # -- deferred to core/ -------------------------------------------------

    def duty_clock(self, crew_id: str, date: str | None = None) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"duty_clock: {self._NOT_YET}")

    def check_legality(self, crew_id: str, pairing_id: str, delay_h: float = 0.0) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"check_legality: {self._NOT_YET}")

    def find_options(self, pairing_id: str, role: str, callout_utc: str | None = None) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"find_options: {self._NOT_YET}")

    def ripple(self, event: dict[str, Any]) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"ripple: {self._NOT_YET}")

    def simulate(self, event: dict[str, Any]) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"simulate: {self._NOT_YET}")

    def joint_plan(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"joint_plan: {self._NOT_YET}")


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


def dispatch(port: ToolPort, name: str, args: dict[str, Any]) -> TraceEntry:
    """Invoke one tool and record it. Never raises — errors become trace rows.

    A tool failure has to reach the model as data so it can route around it;
    an exception here would take the whole turn down instead.
    """
    started = time.perf_counter()

    if name not in TOOL_NAMES:
        return TraceEntry(tool=name, args=args, error=f"unknown tool {name!r}")

    try:
        result = getattr(port, name)(**args)
        error = None
    except ToolError as exc:
        result, error = None, f"{exc.code}: {exc.message}"
    except TypeError as exc:
        result, error = None, f"bad arguments for {name}: {exc}"
    except Exception as exc:  # a tool bug must not kill the turn
        result, error = None, f"{type(exc).__name__}: {exc}"

    return TraceEntry(
        tool=name,
        args=args,
        result=result,
        ms=int((time.perf_counter() - started) * 1000),
        error=error,
    )
