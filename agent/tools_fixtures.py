"""Fixture-backed tool port — the frontend's mock backend.

Satisfies `agent.tools.ToolPort` by serving the generated fixtures in
`evals/fixtures/`, which are reshapes of dCortex's own answer keys. So the
mock returns the *correct* answer, not an invented one, and swapping in
Kashifa's engine is a no-op rather than a rewrite (DECISIONS.md #3).

This exists so Kiran can build the candidate funnel, the rule trace and the
blast-radius view today, instead of waiting on `core/`. Lookups still go to
the real dataset — only the legality-dependent tools are served from fixtures.

Regenerate with `python -m evals.make_fixtures` after any answer-key change.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent import config
from agent.tools import PlaceholderToolPort, ToolError

FIXTURES = config.REPO_ROOT / "evals" / "fixtures"


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    if not FIXTURES.exists():
        return {}
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(FIXTURES.glob("S*.json"))
    }


def _match(**criteria: Any) -> dict[str, Any] | None:
    """Find the scenario whose event mentions any of the given ids."""
    wanted = {str(v) for v in criteria.values() if v}
    if not wanted:
        return None
    for fixture in _load().values():
        event = json.dumps(fixture.get("event", {}))
        if any(w in event for w in wanted):
            return fixture
    return None


class FixtureToolPort(PlaceholderToolPort):
    """Real dataset for lookups; answer-key fixtures for everything else."""

    SCENARIOS = property(lambda self: sorted(_load()))

    def _fixture_or_raise(self, tool: str, **criteria: Any) -> dict[str, Any]:
        fixture = _match(**criteria)
        if fixture is None:
            known = ", ".join(sorted(_load())) or "none generated"
            raise ToolError(
                "UNRESOLVED_ENTITY",
                f"{tool}: no fixture covers {criteria}. Fixtures cover the "
                f"scenarios only ({known}). Run `python -m evals.make_fixtures`, "
                "or wait for core/ (issues #3-#12) for arbitrary inputs.",
            )
        return fixture["answer"]

    def scenario(self, scenario_id: str) -> dict[str, Any]:
        if fixture := _load().get(scenario_id.upper()):
            return fixture
        raise ToolError("UNRESOLVED_ENTITY", f"no fixture {scenario_id!r}")

    # -- fixture-backed tools ---------------------------------------------

    def find_options(
        self, pairing_id: str, role: str, callout_utc: str | None = None
    ) -> dict[str, Any]:
        return self._fixture_or_raise("find_options", pairing_id=pairing_id)

    def joint_plan(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        ids = {e.get("pairing_id") or e.get("crew_id") for e in events or []}
        answer = self._fixture_or_raise("joint_plan", **{f"e{i}": v for i, v in enumerate(ids)})
        if "joint_plan" not in answer:
            raise ToolError("UNRESOLVED_ENTITY", "that fixture is not a joint-plan scenario")
        return answer["joint_plan"]

    def ripple(self, event: dict[str, Any]) -> dict[str, Any]:
        answer = self._fixture_or_raise(
            "ripple", crew_id=event.get("crew_id"), pairing_id=event.get("pairing_id")
        )
        return {
            "uncovered_flights": answer.get("uncovered_flights", []),
            "at_risk_flights": answer.get("at_risk_flights", []),
            "passengers": answer.get("passengers_affected", 0),
            "blast_radius": answer.get("blast_radius") or {
                "nodes": len(answer.get("uncovered_flights", []))
                         + len(answer.get("at_risk_flights", [])),
                "flights": len(answer.get("uncovered_flights", [])),
                "aircraft": 1,
                "passengers": answer.get("passengers_affected", 0),
                "edges": [],
            },
        }

    def simulate(self, event: dict[str, Any]) -> dict[str, Any]:
        answer = self._fixture_or_raise(
            "simulate", crew_id=event.get("crew_id"), pairing_id=event.get("pairing_id"),
            type=event.get("type"),
        )
        return answer.get("world_diff") or {"changed": []}

    def check_legality(
        self, crew_id: str, pairing_id: str, delay_h: float = 0.0
    ) -> dict[str, Any]:
        """Verdicts lifted from a fixture's exclusion list.

        Only crew the answer key actually adjudicated are known here. Anyone
        else raises rather than being reported legal by default — absence of a
        recorded breach is not evidence of legality.
        """
        answer = self._fixture_or_raise("check_legality", pairing_id=pairing_id)

        for row in answer.get("excluded", []):
            if row.get("crew_id") == crew_id:
                return {"crew_id": crew_id, "pairing_id": pairing_id,
                        "legal": False, "verdicts": row.get("verdicts", []),
                        "detail": row.get("reason", "")}

        for option in answer.get("options", []):
            if option.get("crew_id") == crew_id:
                return {"crew_id": crew_id, "pairing_id": pairing_id,
                        "legal": bool(option.get("legal")),
                        "rules_checked": option.get("rules_checked", []),
                        "verdicts": option.get("verdicts", []),
                        "cost_inr": option.get("cost_inr")}

        raise ToolError(
            "UNRESOLVED_ENTITY",
            f"the fixture for {pairing_id} does not adjudicate {crew_id}; "
            "no verdict is available without core/",
        )
