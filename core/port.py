"""`CoreToolPort` — the real engine behind the tool boundary.

Satisfies `agent.tools.ToolPort` by computing answers from the operation
rather than replaying fixtures, so it works for any pairing rather than the
five with published answer keys.

Lookups still delegate to `PostgresToolPort`; this adds the legality-dependent
tools it had to refuse.
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import asdict
from typing import Any

from agent.tools import ToolError
from agent.tools_postgres import PostgresToolPort
from core import rules
from core.engine import Candidate, World, assess, drop_stage, load_world

FUNNEL_ORDER = ("considered", "qualified", "certified", "in position",
                "available", "within limits", "legal")


class CoreToolPort(PostgresToolPort):
    """Postgres for facts, the engine for judgement."""

    def __init__(self, url: str | None = None) -> None:
        super().__init__(url)
        self._world: World | None = None

    @property
    def world(self) -> World:
        if self._world is None:
            self._world = load_world(self)
        return self._world

    # -- legality ---------------------------------------------------------

    def check_legality(self, crew_id: str, pairing_id: str,
                       delay_h: float = 0.0) -> dict[str, Any]:
        c = assess(self.world, crew_id, pairing_id, delay_h)
        return {
            "crew_id": crew_id,
            "pairing_id": pairing_id,
            "legal": c.legal,
            "rules_checked": list(rules.ALL_RULES),
            # RuleVerdict uses slots=True, so it has no __dict__.
            "verdicts": [asdict(v) | {"status": str(v.status)}
                         for v in (rules.blocking(c.verdicts) or c.verdicts[:7])],
            "cost_inr": c.cost_inr,
            "delay_hours": c.delay_hours,
        }

    # -- candidate search -------------------------------------------------

    def find_options(self, role: str, pairing_id: str | None = None,
                     flight_id: str | None = None,
                     callout_utc: str | None = None) -> dict[str, Any]:
        if not pairing_id and flight_id:
            pairing_id = self.pairing_for_flight(flight_id)
        if not pairing_id:
            raise ToolError("UNRESOLVED_ENTITY",
                            "find_options needs a pairing_id or a flight_id")

        world = self.world
        days = world.duty_days(pairing_id)
        incumbent = {c for c, r in world.pairing_crew.get(pairing_id, ()) if r == role}

        pool = [c for c in world.crew.values()
                if c.rank == role and c.crew_id not in incumbent]

        assessed: list[Candidate] = []
        for crew in pool:
            try:
                assessed.append(assess(world, crew.crew_id, pairing_id))
            except ToolError:
                continue

        legal = [c for c in assessed if c.legal]
        excluded = [c for c in assessed if not c.legal]

        # Rank by cost then delay — the answer keys' own ordering.
        legal.sort(key=lambda c: (c.cost_inr, c.delay_hours, c.crew_id))

        options = []
        for i, c in enumerate(legal, start=1):
            options.append({
                "action": c.action(world.crew[c.crew_id].rank),
                "crew_id": c.crew_id, "legal": True,
                "rules_checked": list(rules.ALL_RULES),
                "cost_inr": c.cost_inr, "delay_hours": c.delay_hours, "rank": i,
                "cost_breakdown": c.cost_breakdown,
                "verdicts": [], "blast_radius": 0, "unlock": None,
            })

        # Cancelling is always available and almost always wrong; include it so
        # the comparison is explicit rather than implied.
        n_flights = len(world.pairing_flights.get(pairing_id, []))
        options.append({
            "action": f"Cancel all {n_flights} flights of the pairing",
            "crew_id": None, "legal": True, "rules_checked": [],
            "cost_inr": n_flights * world.costs.cancellation_per_flight,
            "delay_hours": 0.0, "rank": len(options) + 1,
            "cost_breakdown": {"cancellation": n_flights * world.costs.cancellation_per_flight},
            "verdicts": [], "blast_radius": n_flights, "unlock": None,
        })

        # Computed here, not in the renderer: "81x the cost of covering" is a
        # figure the verifier would reject if prose derived it, and it is the
        # single most persuasive number in the answer.
        cheapest = next((o["cost_inr"] for o in options if o["crew_id"]), 0)
        cancel_cost = options[-1]["cost_inr"]
        recommended = next((o for o in options if o["crew_id"]), None)

        # Deltas the prose will reach for, computed here so they are sourced.
        # Claude drafted "5,500 more" (24,000 - 18,500) unprompted: correct
        # arithmetic, but no tool produced it, so the verifier discarded the
        # whole answer. A better model computes a *right* number and is still
        # rejected — sourcing is the test, not correctness.
        tiers = sorted({o["cost_inr"] for o in options if o["crew_id"]})
        return {
            "pairing_id": pairing_id,
            "role": role,
            "recommended": recommended,
            "next_tier_cost_inr": tiers[1] if len(tiers) > 1 else 0,
            "next_tier_premium_inr": (tiers[1] - tiers[0]) if len(tiers) > 1 else 0,
            "cancellation_multiple": round(cancel_cost / cheapest) if cheapest else 0,
            "equal_cost_alternatives": sum(
                1 for o in options if o["crew_id"] and o["cost_inr"] == cheapest) - 1,
            "funnel": self._funnel(assessed, len(pool)),
            "options": options,
            "near_misses": [],
            "excluded": [
                {"crew_id": c.crew_id,
                 "reason": "; ".join(v.detail for v in rules.blocking(c.verdicts)),
                 "rules": [v.rule_id for v in rules.blocking(c.verdicts)]}
                for c in excluded
            ],
        }

    @staticmethod
    def _funnel(assessed: list[Candidate], considered: int) -> list[dict[str, Any]]:
        dropped = Counter(drop_stage(c.verdicts)[0] for c in assessed if not c.legal)
        reasons = {drop_stage(c.verdicts)[0]: drop_stage(c.verdicts)[1]
                   for c in assessed if not c.legal}

        funnel = [{"stage": "considered", "count": considered, "dropped": 0, "reason": ""}]
        remaining = considered
        for stage in FUNNEL_ORDER[1:-1]:
            if not (n := dropped.get(stage, 0)):
                continue
            remaining -= n
            funnel.append({"stage": stage, "count": remaining,
                           "dropped": n, "reason": reasons.get(stage, "")})
        funnel.append({"stage": "legal", "count": remaining, "dropped": 0, "reason": ""})
        return funnel

    # -- cascade ----------------------------------------------------------

    def ripple(self, event: dict[str, Any]) -> dict[str, Any]:
        pairing_id = event.get("pairing_id")
        if not pairing_id and (cid := event.get("crew_id")):
            pairing_id = next(
                (p for p, members in self.world.pairing_crew.items()
                 if any(c == cid for c, _ in members)), None)
        if not pairing_id:
            raise ToolError("UNRESOLVED_ENTITY", "ripple needs a pairing_id or crew_id")

        world = self.world
        days = world.duty_days(pairing_id)
        by_day: dict[Any, list[dict]] = {}
        for f in world.pairing_flights.get(pairing_id, []):
            by_day.setdefault(f["date"], []).append(f)

        first, rest = days[0], days[1:]
        direct = [f["flight_id"] for f in by_day.get(first.date, [])]
        # Later days of a pairing are at risk because it overnights away from
        # base — replacing day 1 alone strands the aircraft where it slept.
        at_risk = [f["flight_id"] for d in rest for f in by_day.get(d.date, [])]
        pax = sum(int(f["seats"]) for f in by_day.get(first.date, []))

        return {
            "pairing_id": pairing_id,
            "uncovered_flights": direct,
            "at_risk_flights": at_risk,
            "passengers": pax,
            "blast_radius": {
                "nodes": len(direct) + len(at_risk) + len(rest),
                "flights": len(direct) + len(at_risk),
                "aircraft": 1,
                "passengers": pax,
                "edges": ([{"from": pairing_id, "to": f, "kind": "direct"} for f in direct]
                          + [{"from": pairing_id, "to": f, "kind": "orphaned-day"}
                             for f in at_risk]),
            },
        }

    # -- joint assignment -------------------------------------------------

    def joint_plan(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        """Cost-minimal cover across simultaneous disruptions.

        The constraint that makes this joint is disjointness: one crew member
        cannot cover two pairings at once. Without it you assign the cheapest
        reserve to both and produce an infeasible plan (DECISIONS.md #6).

        Ties are normal — S6 has twenty equally optimal assignments — so the
        count is reported rather than one being presented as uniquely right.
        """
        pairings = [e.get("pairing_id") for e in events or [] if e.get("pairing_id")]
        if len(pairings) < 2:
            raise ToolError("UNRESOLVED_ENTITY",
                            "joint_plan needs at least two pairing_ids")

        role = (events[0] or {}).get("role", "Captain")
        per = [self.find_options(role=role, pairing_id=p)["options"] for p in pairings]
        crewed = [[o for o in opts if o["crew_id"]] for opts in per]

        best: tuple[int, tuple[dict, ...]] | None = None
        ties = 0
        for combo in itertools.product(*(opts[:12] for opts in crewed)):
            ids = [o["crew_id"] for o in combo]
            if len(set(ids)) != len(ids):
                continue  # disjointness
            total = sum(o["cost_inr"] for o in combo)
            if best is None or total < best[0]:
                best, ties = (total, combo), 1
            elif total == best[0]:
                ties += 1

        if best is None:
            raise ToolError("NO_LEGAL_OPTION", "no disjoint assignment covers all pairings")

        total, combo = best
        return {
            "total_cost_inr": total,
            "equal_cost_alternatives": ties,
            **{f"assign_{p}": o for p, o in zip(pairings, combo)},
            "note": ("The same crew member cannot cover two pairings. Where several "
                     "assignments cost the same they are equally correct."),
        }

    def simulate(self, event: dict[str, Any]) -> dict[str, Any]:
        """What-if, expressed as the difference a perturbation makes."""
        delay = float(event.get("delay_hours") or 0)
        pairing_id = event.get("pairing_id")
        if not pairing_id:
            raise ToolError("UNRESOLVED_ENTITY", "simulate needs a pairing_id")

        world = self.world
        changed = []
        for crew_id, role in world.pairing_crew.get(pairing_id, ()):
            before = assess(world, crew_id, pairing_id, 0.0)
            after = assess(world, crew_id, pairing_id, delay)
            if before.legal != after.legal:
                changed.append({
                    "crew_id": crew_id, "role": role,
                    "legal_before": before.legal, "legal_after": after.legal,
                    "detail": "; ".join(v.detail for v in rules.blocking(after.verdicts)),
                })
        return {"pairing_id": pairing_id, "delay_hours": delay, "changed": changed}
