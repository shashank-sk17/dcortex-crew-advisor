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

import re
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
            "Returns the candidate funnel with a reason for every drop. "
            "Identify by pairing_id, or by flight_id if you only know the leg. "
            "Never construct an id from a route like 'BLR->BOM' — look it up."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pairing_id": {"type": "string", "pattern": "^P-[0-9]{4}$"},
                "flight_id": {
                    "type": "string",
                    "pattern": "^DX[0-9]{3}-[0-9]{4}-[0-9]{2}-[0-9]{2}$",
                    "description": (
                        "Alternative to pairing_id when the disruption is named "
                        "by flight. The pairing is resolved for you."
                    ),
                },
                "crew_id": {
                    "type": "string", "pattern": "^C-[0-9]{4}$",
                    "description": (
                        "The crew member who is unavailable. Their pairing AND "
                        "role are resolved from the roster, so neither has to "
                        "be supplied or guessed."
                    ),
                },
                "role": {
                    "type": "string",
                    "enum": ["Captain", "First Officer", "Senior Cabin Crew", "Cabin Crew"],
                    "description": "Inferred from crew_id when that is given.",
                },
                "callout_utc": {"type": "string", "description": "ISO-8601 UTC"},
            },
            "required": [],
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
# Filter guard rails
#
# Measured over the 16 tier-1 gold questions on qwen3:8b: 12 produced a failed
# call, every one of them an invented column name. The guesses were not random
# — they were the *semantically right* field under a plausible other name
# (`departure` for `dep_station`, `expiry_date` for `valid_to`). So three
# layers, in order of preference:
#
#   1. tell the model the real column names   (schema enrichment, below)
#   2. map a near-miss onto the real one      (FIELD_ALIASES)
#   3. reject loudly, naming what is valid    (resolve_filters)
#
# Guarding alone would only convert a wrong answer into a failed one; the model
# still has to be able to succeed.
# --------------------------------------------------------------------------

FIELD_ALIASES: dict[str, str] = {
    # station fields
    "departure": "dep_station", "origin": "dep_station", "from": "dep_station",
    "departure_station": "dep_station", "dep": "dep_station",
    "destination": "arr_station", "arrival": "arr_station", "to": "arr_station",
    "arrival_station": "arr_station", "arr": "arr_station",
    # identity
    "crew": "crew_id", "crewid": "crew_id", "employee_id": "crew_id",
    "pairing": "pairing_id", "flight": "flight_no", "flight_number": "flight_no",
    "aircraft_registration": "aircraft", "tail": "aircraft", "registration": "aircraft",
    # certifications
    "expiry_date": "valid_to", "expiry": "valid_to", "expires": "valid_to",
    "expires_on": "valid_to", "valid_until": "valid_to", "cert": "cert_type",
    "certification": "cert_type", "type": "cert_type",
    # misc
    "station": "base", "home_base": "base", "rank_name": "rank",
    "role": "rank", "position": "rank", "job": "rank",
    "aircraft_rating": "ratings", "rating": "ratings",
}


def resolve_filters(
    entity: str, filters: dict[str, Any] | None, known: frozenset[str] | set[str]
) -> dict[str, Any]:
    """Map filter keys onto real columns, or fail naming the valid ones.

    `known` comes from the live backend, so JSON and Postgres each get their
    own column set rather than sharing one hardcoded list.
    """
    resolved: dict[str, Any] = {}
    for key, value in (filters or {}).items():
        if key in known:
            resolved[key] = value
            continue
        alias = FIELD_ALIASES.get(key.lower().replace(" ", "_"))
        if alias and alias in known:
            resolved[alias] = value
            continue
        raise ToolError(
            "UNRESOLVED_ENTITY",
            f"{entity} has no field {key!r}. Valid fields: {', '.join(sorted(known))}",
        )
    return resolved


def schemas_for_port(port: Any) -> list[dict[str, Any]]:
    """TOOL_SCHEMAS with `lookup` enriched by the backend's real field names.

    Without this the model is guessing at column names from the entity name
    alone, which is where nearly every tier-1 tool failure came from.
    """
    describe = getattr(port, "entity_fields", None)
    if describe is None:
        return TOOL_SCHEMAS

    lines = []
    for entity in sorted(getattr(port, "ENTITIES", ()) or ()):
        try:
            fields = sorted(describe(entity))
        except Exception:
            continue
        lines.append(f"  {entity}: {', '.join(fields)}")
    if not lines:
        return TOOL_SCHEMAS

    enriched = []
    for tool in TOOL_SCHEMAS:
        if tool["name"] != "lookup":
            enriched.append(tool)
            continue
        clone = {**tool, "input_schema": {**tool["input_schema"],
                                          "properties": {**tool["input_schema"]["properties"]}}}
        clone["input_schema"]["properties"]["filters"] = {
            "type": "object",
            "description": (
                "Field equality filters. Use ONLY these field names — any other "
                "key is rejected:\n" + "\n".join(lines)
            ),
        }
        enriched.append(clone)
    return enriched


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

    SOURCES = {
        "crew": "crew", "flights": "flights", "reserves": "reserve_pool",
        "certifications": "certifications", "risk_signals": "risk_signals",
        "costs": "costs", "pairings": "rosters",
    }
    ENTITIES = tuple(SOURCES)

    def _rows(self, entity: str) -> list[dict[str, Any]]:
        source = self.SOURCES.get(entity)
        if source is None:
            raise ToolError("UNRESOLVED_ENTITY", f"unknown entity {entity!r}")
        rows = self._load(source)
        if entity == "pairings":
            rows = rows["pairings"]
        return [rows] if isinstance(rows, dict) else rows

    def entity_fields(self, entity: str) -> frozenset[str]:
        rows = self._rows(entity)
        return frozenset(rows[0].keys()) if rows else frozenset()

    def pairing_for_flight(self, flight_id: str) -> str:
        """Which pairing operates a given leg.

        A controller names a disruption by route or flight ("captain of
        BLR->BOM is out"), but cover is found per *pairing* — crew fly whole
        pairings, not single legs. Without this hop the model invents a
        pairing id from the route, which is how "BLR->BOM" ended up being
        passed as one.
        """
        for pairing in self._rows("pairings"):
            for day in pairing.get("days", []):
                if flight_id in day.get("flights", []):
                    return pairing["pairing_id"]
        raise ToolError("UNRESOLVED_ENTITY", f"no pairing operates {flight_id!r}")

    def lookup(self, entity: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        rows = self._rows(entity)
        for key, want in resolve_filters(entity, filters, self.entity_fields(entity)).items():
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


def validate_args(name: str, args: dict[str, Any]) -> None:
    """Check arguments against the tool's own JSON Schema before calling it.

    The schemas already carry patterns like `^P-[0-9]{4}$`; nothing was
    enforcing them, so `find_options(pairing_id="BLR->BOM")` reached the port
    and failed there with a message about missing fixtures rather than about
    the malformed id. Catching it here says what is actually wrong.
    """
    schema = next((t["input_schema"] for t in TOOL_SCHEMAS if t["name"] == name), None)
    if not schema:
        return
    props = schema.get("properties", {})

    for key, value in args.items():
        spec = props.get(key)
        if not spec or value is None:
            continue
        if (pattern := spec.get("pattern")) and isinstance(value, str):
            if not re.fullmatch(pattern, value):
                raise ToolError(
                    "UNRESOLVED_ENTITY",
                    f"{name}: {key}={value!r} is not a valid identifier "
                    f"(expected {pattern}). Look the value up first rather "
                    f"than constructing it.",
                )
        if (allowed := spec.get("enum")) and value not in allowed:
            raise ToolError(
                "UNRESOLVED_ENTITY",
                f"{name}: {key}={value!r} is not one of {', '.join(map(str, allowed))}",
            )

    for required in schema.get("required", []):
        if required not in args:
            raise ToolError("UNRESOLVED_ENTITY", f"{name}: {required!r} is required")


def dispatch(port: ToolPort, name: str, args: dict[str, Any]) -> TraceEntry:
    """Invoke one tool and record it. Never raises — errors become trace rows.

    A tool failure has to reach the model as data so it can route around it;
    an exception here would take the whole turn down instead.
    """
    started = time.perf_counter()

    if name not in TOOL_NAMES:
        return TraceEntry(tool=name, args=args, error=f"unknown tool {name!r}")

    try:
        validate_args(name, args)
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
