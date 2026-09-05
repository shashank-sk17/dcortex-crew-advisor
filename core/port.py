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
from datetime import timedelta
from typing import Any

from agent import config
from agent.tools import ToolError
from agent.tools_postgres import PostgresToolPort
from core import rules
from core.engine import Candidate, World, assess, drop_stage, load_world
from core.gates import GateWorld, iso, load_gates, next_at_gate, occupant_at, parse
from core.resolve import Resolution, resolve

FUNNEL_ORDER = ("considered", "qualified", "certified", "in position",
                "available", "within limits", "legal")


class CoreToolPort(PostgresToolPort):
    """Postgres for facts, the engine for judgement."""

    def __init__(self, url: str | None = None) -> None:
        super().__init__(url)
        self._world: World | None = None
        self._gates: GateWorld | None = None

    @property
    def world(self) -> World:
        if self._world is None:
            self._world = load_world(self)
        return self._world

    @property
    def gates(self) -> GateWorld:
        if self._gates is None:
            self._gates = load_gates(self)
        return self._gates

    # -- entity resolution -------------------------------------------------

    def _universe(self, kind: str) -> tuple[dict[str, Any], Any]:
        """The valid id space for one kind, and how to describe a member.

        The label matters as much as the id: "C-1024" alone is not something a
        controller can confirm against, but "C-1024 (First Officer, DEL)" is.
        """
        w = self.world
        if kind == "crew":
            return w.crew, lambda c: f"{c.rank}, {c.base}, {'/'.join(c.ratings)}"
        if kind == "pairing":
            return (
                w.pairing_days,
                lambda days: (f"{len(days)} day{'s' if len(days) > 1 else ''} from "
                              f"{days[0].date}, {days[0].dep_station}"),
            )
        if kind == "flight":
            flights = {f["flight_id"]: f
                       for legs in w.pairing_flights.values() for f in legs}
            return (flights,
                    lambda f: f"{f['dep_station']}->{f['arr_station']} {f['date']}")
        raise ToolError("INTERNAL", f"no id universe for {kind!r}")

    def require(self, kind: str, value: str | None) -> str:
        """Confirm an id is real, or raise something a controller can act on.

        Never substitutes a near match. `C-1042` and `C-1024` differ by one
        transposed digit; in this dataset one is a captain and the other is
        nobody. Silently correcting would dispatch a different human being to
        an aircraft — so a near match is returned as a question, not an answer.
        """
        if not value:
            raise ToolError("UNRESOLVED_ENTITY", f"a {kind} id is required")

        universe, label = self._universe(kind)
        result = resolve(kind, value, universe, label)
        if result.exists:
            return value

        raise ToolError(
            "NEEDS_CONFIRMATION" if result.needs_confirmation else "UNRESOLVED_ENTITY",
            result.message(),
        )

    # -- legality ---------------------------------------------------------

    def resolve_flight(self, flight_id: str | None = None,
                       flight_no: str | None = None,
                       date: str | None = None) -> str:
        """A flight id from whatever the controller named.

        A bare flight number is ambiguous: DX412 operates on three separate
        days in this week alone, each on a different pairing. Picking one
        silently would answer a question nobody asked, so an undated flight
        number comes back as a request for the date.
        """
        if flight_id:
            self.require("flight", flight_id)
            return flight_id
        if not flight_no:
            raise ToolError("UNRESOLVED_ENTITY", "no flight was named")

        rows = self.lookup("flights", {"flight_no": flight_no})
        if not rows:
            raise ToolError("UNRESOLVED_ENTITY", f"there is no flight {flight_no}")

        if date:
            match = [r for r in rows if str(r["date"]) == str(date)]
            if not match:
                flew = ", ".join(sorted(str(r["date"]) for r in rows))
                raise ToolError(
                    "UNRESOLVED_ENTITY",
                    f"{flight_no} does not operate on {date}. It flies on {flew}.")
            return match[0]["flight_id"]

        if len(rows) == 1:
            return rows[0]["flight_id"]

        flew = ", ".join(sorted(str(r["date"]) for r in rows))
        raise ToolError(
            "AMBIGUOUS_QUERY",
            f"{flight_no} operates on {flew}. Which date do you mean? "
            f"Each is a different pairing, so the answer differs.")

    # -- boarding gate ------------------------------------------------------

    def check_gate(self, flight_id: str | None = None, flight_no: str | None = None,
                   date: str | None = None, boarding_gate_number: str | None = None,
                   delay_minutes: float = 0.0, at_utc: str | None = None) -> dict[str, Any]:
        gates = self.gates

        # No flight named: a pure occupancy question -- "is BLR-G1 blocked
        # right now / at this instant". Free ends up meaning no aircraft
        # holds the gate in that instant, not that nothing operates through it.
        if not flight_id and not flight_no and boarding_gate_number:
            if boarding_gate_number not in gates.by_gate:
                raise ToolError(
                    "UNRESOLVED_ENTITY",
                    f"there is no boarding gate {boarding_gate_number!r}. "
                    f"Known gates: {', '.join(sorted(gates.by_gate))}")
            instant = parse(at_utc) if at_utc else parse(config.SNAPSHOT_UTC)
            occupant = occupant_at(gates, boarding_gate_number, instant)
            return {
                "boarding_gate_number": boarding_gate_number,
                "checked_at_utc": at_utc or config.SNAPSHOT_UTC,
                "occupied": occupant is not None,
                "occupying_flight_id": occupant["flight_id"] if occupant else None,
                "occupying_pairing_id": occupant["pairing_id"] if occupant else None,
                "occupied_from": occupant["boarding_start_time"] if occupant else None,
                "occupied_until": occupant["boarding_end_time"] if occupant else None,
            }

        # Named by flight. resolve_flight already reports a wrong date by
        # naming the dates the flight actually operates on -- exactly the
        # "correct gate, wrong date" case, so nothing extra is needed for it.
        fid = self.resolve_flight(flight_id, flight_no, date)
        record = gates.by_flight.get(fid)
        if record is None:
            raise ToolError("UNRESOLVED_ENTITY",
                            f"{fid} has no boarding-gate record in the mock dataset")

        actual_gate = record["boarding_gate_number"]
        end = parse(record["boarding_end_time"])
        if delay_minutes:
            end += timedelta(minutes=delay_minutes)

        conflict = None
        if delay_minutes:
            nxt = next_at_gate(gates, actual_gate, fid)
            if nxt is not None:
                nxt_start = parse(nxt["boarding_start_time"])
                if end > nxt_start:
                    conflict = {
                        "flight_id": nxt["flight_id"],
                        "pairing_id": nxt["pairing_id"],
                        "its_boarding_start_time": nxt["boarding_start_time"],
                        "overlap_minutes": round((end - nxt_start).total_seconds() / 60, 1),
                    }

        return {
            "flight_id": fid,
            "pairing_id": record["pairing_id"],
            "date": record["date"],
            "actual_boarding_gate_number": actual_gate,
            "claimed_boarding_gate_number": boarding_gate_number,
            "gate_match": boarding_gate_number is None or boarding_gate_number == actual_gate,
            "boarding_start_time": record["boarding_start_time"],
            "boarding_end_time": record["boarding_end_time"],
            "delay_minutes": delay_minutes,
            "delayed_boarding_end_time": iso(end) if delay_minutes else None,
            "gate_conflict": conflict,
        }

    def check_legality(self, crew_id: str, pairing_id: str | None = None,
                       flight_id: str | None = None, flight_no: str | None = None,
                       date: str | None = None,
                       delay_h: float = 0.0) -> dict[str, Any]:
        self.require("crew", crew_id)
        if not pairing_id:
            # "Move C-2087 onto DX412" names a leg. Crew fly whole pairings,
            # so the leg has to be resolved to the trip it belongs to.
            pairing_id = self.pairing_for_flight(
                self.resolve_flight(flight_id, flight_no, date))
        self.require("pairing", pairing_id)
        c = assess(self.world, crew_id, pairing_id, delay_h)
        subject = self.world.crew[crew_id]
        return {
            "crew_id": crew_id,
            "name": subject.name,
            "rank": subject.rank,
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

    def assignment_for_crew(self, crew_id: str) -> tuple[str, str]:
        """Which pairing a crew member is on, and in what role.

        "C-1042 is sick" names a person, not a trip. The roster knows both the
        pairing and the role, so neither has to be guessed — and the role
        matters: replacing a captain with a first officer is not cover.
        """
        self.require("crew", crew_id)
        for pairing_id, members in self.world.pairing_crew.items():
            for member, role in members:
                if member == crew_id:
                    return pairing_id, role
        raise ToolError("UNRESOLVED_ENTITY",
                        f"{crew_id} is not rostered on any pairing this week")

    def risk_scores(self) -> dict[str, float]:
        """Pre-computed disruption risk, per crew member.

        dCortex provides these and is explicit that teams do not model them:
        "treat them like a weather forecast; your job is what the controller
        does about it." So they ride alongside an option as information and
        never enter the ranking — a risk score is not a rule, and letting one
        reorder legal options would be exactly the prediction we were told
        not to build.
        """
        return {r["crew_id"]: float(r["disruption_risk_score"])
                for r in self.lookup("risk_signals")
                if r.get("disruption_risk_score") is not None}

    def find_options(self, role: str | None = None, pairing_id: str | None = None,
                     flight_id: str | None = None, crew_id: str | None = None,
                     callout_utc: str | None = None) -> dict[str, Any]:
        if not pairing_id and crew_id:
            pairing_id, rostered_role = self.assignment_for_crew(crew_id)
            role = role or rostered_role
        if not pairing_id and flight_id:
            pairing_id = self.pairing_for_flight(flight_id)
        if pairing_id:
            self.require("pairing", pairing_id)
        if not pairing_id:
            raise ToolError("UNRESOLVED_ENTITY",
                            "find_options needs a pairing_id, flight_id or crew_id")
        if not role:
            raise ToolError("UNRESOLVED_ENTITY",
                            "find_options needs a role, or a crew_id to infer it from")

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

        risk = self.risk_scores()
        options = []
        for i, c in enumerate(legal, start=1):
            who = world.crew[c.crew_id]
            options.append({
                "action": c.action(who.rank, who.name),
                "crew_id": c.crew_id, "legal": True,
                "name": who.name, "seniority": who.seniority,
                "base": who.base, "reachability_minutes": who.reachability_minutes,
                # Provided input, treated like a weather forecast: reported
                # beside the option, never allowed to change its legality or
                # its rank. dCortex is explicit that teams do not model this.
                "disruption_risk_score": risk.get(c.crew_id),
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
                 "name": world.crew[c.crew_id].name,
                 "rank": world.crew[c.crew_id].rank,
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
        if pairing_id:
            self.require("pairing", pairing_id)
        if not pairing_id and (cid := event.get("crew_id")):
            self.require("crew", cid)
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
