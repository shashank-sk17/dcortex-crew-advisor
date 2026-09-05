"""The schema the model reads must match the port that runs.

Every failure of this kind has looked the same from the outside: the model
makes a perfectly reasonable call, and the tool rejects it as bad arguments.

    find_options: got an unexpected keyword argument 'crew_id'
    find_options: missing 1 required positional argument: 'role'
    find_options needs a pairing_id, flight_id or crew_id   ← asked for DX401

In each case the schema advertised something the port could not accept. The
model was doing what it was told; the contract was a lie. `ToolPort` is a
`typing.Protocol`, so nothing checks this at import — the drift only shows up
mid-conversation, as a tool error a controller sees.

These tests are the check that Protocol cannot give us. They compare the JSON
Schema passed to the model against the actual signatures of every port, so a
property added to one and not the other fails here rather than in front of a
user.
"""

from __future__ import annotations

import inspect

import pytest

from agent.entities import extract
from agent.tools import TOOL_NAMES, TOOL_SCHEMAS, PlaceholderToolPort


def _ports():
    """Every port implementation, without instantiating any of them.

    Signatures are a property of the class; PostgresToolPort wants a database
    and CoreToolPort loads the world, and neither is needed to read a `def`.
    """
    ports = [PlaceholderToolPort]
    from agent.tools_postgres import PostgresToolPort

    ports.append(PostgresToolPort)
    try:
        from core.port import CoreToolPort
    except Exception:  # pragma: no cover - core is optional at import time
        pass
    else:
        ports.append(CoreToolPort)
    return ports


def _accepts(func, name: str) -> bool:
    sig = inspect.signature(func)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return True
    return name in sig.parameters


SCHEMA_PROPS = [
    (schema["name"], prop)
    for schema in TOOL_SCHEMAS
    for prop in schema["input_schema"].get("properties", {})
]


@pytest.mark.parametrize("tool_name,prop", SCHEMA_PROPS)
@pytest.mark.parametrize("port", _ports(), ids=lambda p: p.__name__)
def test_every_schema_property_is_accepted_by_every_port(port, tool_name, prop):
    """A property the model is offered must be one the port can take."""
    method = getattr(port, tool_name, None)
    assert method is not None, f"{port.__name__} has no {tool_name}()"
    assert _accepts(method, prop), (
        f"{port.__name__}.{tool_name}() rejects '{prop}', which the tool "
        f"schema offers the model. The model will call it and get a bad-"
        f"arguments error."
    )


@pytest.mark.parametrize("port", _ports(), ids=lambda p: p.__name__)
def test_no_schema_argument_is_required_positionally(port):
    """Every schema property must be optional in the signature.

    JSON Schema says which fields are required; a positional parameter says it
    a second time and disagrees. `find_options(self, role, ...)` required a
    role the schema listed as optional, so `find_options(crew_id=...)` — the
    documented way to call it — raised TypeError.
    """
    for schema in TOOL_SCHEMAS:
        method = getattr(port, schema["name"], None)
        if method is None:
            continue
        required = set(schema["input_schema"].get("required", []))
        for name, param in inspect.signature(method).parameters.items():
            if name in ("self", "kwargs", "args") or name in required:
                continue
            if param.kind in (inspect.Parameter.VAR_KEYWORD,
                              inspect.Parameter.VAR_POSITIONAL):
                continue
            assert param.default is not inspect.Parameter.empty, (
                f"{port.__name__}.{schema['name']}() requires '{name}', but "
                f"the schema does not list it in `required`."
            )


def test_a_flight_named_by_number_can_reach_find_options():
    """"I need a pilot for DX401" — the regression this file was written for.

    The extractor produces `flight_nos`, and before this the only flight field
    find_options accepted was `flight_id` (DX401-2026-09-15). The entity had
    nowhere to go and the tool answered "needs a pairing_id, flight_id or
    crew_id" while holding a perfectly good flight number.
    """
    ents = extract("i need a pilot for DX401")
    assert ents.flight_nos == ["DX401"]

    schema = next(t for t in TOOL_SCHEMAS if t["name"] == "find_options")
    props = schema["input_schema"]["properties"]
    assert "flight_no" in props, "a flight number cannot be passed to find_options"

    for port in _ports():
        assert _accepts(port.find_options, "flight_no"), port.__name__


def test_every_schema_names_a_real_tool():
    assert {t["name"] for t in TOOL_SCHEMAS} == set(TOOL_NAMES)
