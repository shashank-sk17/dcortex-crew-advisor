"""The reasoning core — candidate search, cost ranking and cascade.

Loads the whole operation from Postgres once, then answers from memory. The
dataset is under 700 KB (DECISIONS.md #1), so a per-question round trip buys
nothing; `CoreToolPort` holds one immutable `World` and forks it for what-ifs.

Correctness is checked against dCortex's six scenario answer keys rather than
asserted — see `core/tests/test_engine.py`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Any

from agent.schemas import RuleVerdict
from agent.tools import ToolError, resolve_filters
from agent.tools_postgres import PostgresToolPort
from core import rules
from core.duty import DutyDay, format_hours, hours_between
from core.rules import ALL_RULES, CrewSnapshot

PILOT_ROLES = ("Captain", "First Officer")

# RULE-BASE-07: the DEL->BLR positioning flights, from the dataset README.
# New report is arrival + 15 min.
POSITIONING = {
    ("DEL", "BLR"): (
        ("DX402", time(8, 45), "odd"),
        ("DX589", time(7, 45), "even"),
    )
}
POSITIONING_REPORT_BUFFER = timedelta(minutes=15)


@dataclass(slots=True)
class Costs:
    reserve_pilot: int
    reserve_cabin: int
    dayoff_pilot: int
    dayoff_cabin: int
    deadhead: int
    delay_per_hour: int
    cancellation_per_flight: int

    def callout(self, role: str, on_reserve: bool) -> int:
        pilot = role in PILOT_ROLES
        if on_reserve:
            return self.reserve_pilot if pilot else self.reserve_cabin
        return self.dayoff_pilot if pilot else self.dayoff_cabin


@dataclass
class World:
    """The whole operation, in memory."""

    crew: dict[str, CrewSnapshot]
    pairing_days: dict[str, list[DutyDay]]
    pairing_crew: dict[str, list[tuple[str, str]]]      # pairing -> [(crew, role)]
    pairing_flights: dict[str, list[dict[str, Any]]]
    reserves: dict[str, list[tuple[date, time, time]]]  # crew -> [(date, start, end)]
    costs: Costs

    def duty_days(self, pairing_id: str) -> list[DutyDay]:
        if pairing_id not in self.pairing_days:
            raise ToolError("UNRESOLVED_ENTITY", f"no pairing {pairing_id!r}")
        return self.pairing_days[pairing_id]

    def on_reserve(self, crew_id: str, when: date, report: datetime) -> bool:
        """A reserve is usable only if the required report falls in the window.

        Not the disruption time and not the departure — the report time, after
        any positioning. Getting this wrong makes unavailable reserves look
        available, which is the expensive direction to be wrong in.
        """
        for day, start, end in self.reserves.get(crew_id, ()):
            if day == when and start <= report.timetz().replace(tzinfo=None) <= end:
                return True
        return False


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_world(port: PostgresToolPort) -> World:
    q = port._query

    daily_duty: dict[str, dict[date, float]] = defaultdict(dict)
    daily_flight: dict[str, dict[date, float]] = defaultdict(dict)
    for r in q("select crew_id, date, duty_hours, flight_hours from duty_daily_history"):
        daily_duty[r["crew_id"]][r["date"]] = float(r["duty_hours"])
        daily_flight[r["crew_id"]][r["date"]] = float(r["flight_hours"])

    certs: dict[str, list[tuple[str, date, date]]] = defaultdict(list)
    for r in q("select crew_id, cert_type, valid_from, valid_to from certifications"):
        certs[r["crew_id"]].append((r["cert_type"], r["valid_from"], r["valid_to"]))

    clocks = {r["crew_id"]: r["last_rest_ended"]
              for r in q("select crew_id, last_rest_ended from duty_clocks")}

    # Pairing days, with sector count and origin from the legs they contain.
    flights = {r["flight_id"]: r for r in q(
        "select flight_id, date, dep_station, arr_station, dep_utc, arr_utc, "
        "block_hours, aircraft_type, seats from flights")}

    legs: dict[tuple[str, date], list[dict]] = defaultdict(list)
    for r in q("select pairing_id, date, flight_id, leg_order "
               "from pairing_day_flights order by pairing_id, date, leg_order"):
        if f := flights.get(r["flight_id"]):
            legs[(r["pairing_id"], r["date"])].append(f)

    pairing_days: dict[str, list[DutyDay]] = defaultdict(list)
    pairing_flights: dict[str, list[dict]] = defaultdict(list)
    for r in q("select pairing_id, date, report_utc, release_utc from pairing_days "
               "order by pairing_id, date"):
        day_legs = legs.get((r["pairing_id"], r["date"]), [])
        if not day_legs:
            continue
        pairing_days[r["pairing_id"]].append(DutyDay(
            date=r["date"],
            report_utc=r["report_utc"],
            release_utc=r["release_utc"],
            n_sectors=len(day_legs),
            block_hours=round(sum(float(f["block_hours"]) for f in day_legs), 2),
            aircraft_type=day_legs[0]["aircraft_type"],
            dep_station=day_legs[0]["dep_station"],
        ))
        pairing_flights[r["pairing_id"]].extend(day_legs)

    pairing_crew: dict[str, list[tuple[str, str]]] = defaultdict(list)
    assigned: dict[str, list[tuple[str, datetime, datetime]]] = defaultdict(list)
    for r in q("select pairing_id, crew_id, role from pairing_crew"):
        pairing_crew[r["pairing_id"]].append((r["crew_id"], r["role"]))
        for day in pairing_days.get(r["pairing_id"], []):
            assigned[r["crew_id"]].append((r["pairing_id"], day.report_utc, day.release_utc))

    crew = {}
    for r in q("select crew_id, rank, base, ratings, status, reachability_minutes from crew"):
        cid = r["crew_id"]
        crew[cid] = CrewSnapshot(
            crew_id=cid, rank=r["rank"], base=r["base"],
            ratings=tuple(r["ratings"] or ()), status=r["status"],
            reachability_minutes=r["reachability_minutes"],
            last_rest_ended=clocks.get(cid),
            daily_duty=daily_duty.get(cid, {}), daily_flight=daily_flight.get(cid, {}),
            certs=tuple(certs.get(cid, ())), assigned=tuple(assigned.get(cid, ())),
        )

    reserves: dict[str, list[tuple[date, time, time]]] = defaultdict(list)
    for r in q("select crew_id, dates, oncall_start_utc, oncall_end_utc from reserve_pool"):
        for d in r["dates"] or []:
            reserves[r["crew_id"]].append((d, r["oncall_start_utc"], r["oncall_end_utc"]))

    c = q("select * from costs limit 1")[0]
    return World(
        crew=crew, pairing_days=dict(pairing_days), pairing_crew=dict(pairing_crew),
        pairing_flights=dict(pairing_flights), reserves=dict(reserves),
        costs=Costs(
            reserve_pilot=c["reserve_callout_pilot"], reserve_cabin=c["reserve_callout_cabin"],
            dayoff_pilot=c["dayoff_callout_pilot"], dayoff_cabin=c["dayoff_callout_cabin"],
            deadhead=c["deadhead_positioning"],
            delay_per_hour=c["delay_cost_per_duty_hour"],
            cancellation_per_flight=c["cancellation_per_flight"],
        ),
    )


# --------------------------------------------------------------------------
# Candidate search
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Candidate:
    crew_id: str
    verdicts: list[RuleVerdict]
    on_reserve: bool
    deadhead: bool
    delay_hours: float
    cost_inr: int
    cost_breakdown: dict[str, int]

    @property
    def legal(self) -> bool:
        return rules.is_legal(self.verdicts)

    def action(self, rank_name: str) -> str:
        kind = "reserve callout" if self.on_reserve else "day-off callout"
        if self.deadhead:
            kind += (f" + deadhead (first departure delayed "
                     f"~{self.delay_hours}h)")
        return f"Assign {rank_name} {self.crew_id} ({kind})"


def positioning_delay(world: World, crew: CrewSnapshot, day: DutyDay) -> float | None:
    """Hours the departure must slip so a positioned crew can report.

    Returns None when no same-day positioning flight exists, which is the
    RULE-BASE-07 exclusion.
    """
    options = POSITIONING.get((crew.base, day.dep_station))
    if not options:
        return None

    best: float | None = None
    for _, arrival, parity in options:
        if (day.date.day % 2 == 1) != (parity == "odd"):
            continue
        arrives = datetime.combine(day.date, arrival, tzinfo=day.report_utc.tzinfo)
        new_report = arrives + POSITIONING_REPORT_BUFFER
        slip = max(0.0, hours_between(day.report_utc, new_report))
        if best is None or slip < best:
            best = slip
    return best


def assess(world: World, crew_id: str, pairing_id: str,
           delay_hours: float = 0.0) -> Candidate:
    """Evaluate one crew member against one pairing."""
    crew = world.crew.get(crew_id)
    if crew is None:
        raise ToolError("UNRESOLVED_ENTITY", f"no crew {crew_id!r}")

    days = world.duty_days(pairing_id)
    first = days[0]

    deadhead = crew.base != first.dep_station
    slip = delay_hours
    if deadhead:
        needed = positioning_delay(world, crew, first)
        if needed is None:
            verdicts = [rules.check_base(crew, first, deadhead=False)]
            return Candidate(crew_id, verdicts, False, True, 0.0, 0, {})
        slip = max(slip, needed)

    shifted = [d.delayed(slip) if slip else d for d in days]
    on_reserve = world.on_reserve(crew_id, first.date, shifted[0].report_utc)
    verdicts = rules.evaluate(crew, shifted, exclude_pairing=pairing_id, deadhead=deadhead)

    # Rostered on reserve that day, but the window does not cover the required
    # report: they are unavailable, not a day-off callout. Someone on reserve
    # duty is not on a day off, so falling back to day-off pricing invents an
    # option the desk does not actually have.
    rostered_reserve = any(d == first.date for d, _, _ in world.reserves.get(crew_id, ()))
    if rostered_reserve and not on_reserve:
        window = next(
            (f"{s:%H:%M}-{e:%H:%M}Z" for d, s, e in world.reserves[crew_id]
             if d == first.date), "")
        verdicts.append(rules._fail(
            "RULE-BASE-07",
            f"reserve on-call window {window} does not cover required report "
            f"{shifted[0].report_utc:%H:%M}Z",
            date=first.date.isoformat(),
        ))

    if deadhead and not on_reserve:
        # Positioning is only offered to reserves in this dataset.
        on_reserve = any(d == first.date for d, _, _ in world.reserves.get(crew_id, ()))

    breakdown = {"callout": world.costs.callout(crew.rank, on_reserve)}
    if deadhead:
        breakdown["positioning"] = world.costs.deadhead
    if slip:
        breakdown["delay"] = int(round(slip * world.costs.delay_per_hour))

    return Candidate(
        crew_id=crew_id, verdicts=verdicts, on_reserve=on_reserve,
        deadhead=deadhead, delay_hours=round(slip, 2),
        cost_inr=sum(breakdown.values()), cost_breakdown=breakdown,
    )


def drop_stage(verdicts: list[RuleVerdict]) -> tuple[str, str]:
    """Which funnel stage a candidate fell out at, and why."""
    for v in verdicts:
        if not v.failed:
            continue
        return {
            "RULE-QUAL-05": ("qualified", "no rating / not active"),
            "RULE-CERT-06": ("certified", "certification invalid on a duty date"),
            "RULE-BASE-07": ("in position", "no same-day positioning from base"),
            "RULE-REST-04": ("available", "rest conflict or double-booked"),
            "RULE-FDP-01": ("within limits", "flight duty period exceeded"),
            "RULE-DUTY-02": ("within limits", "duty-hour limit exceeded"),
            "RULE-FLT-03": ("within limits", "block-hour limit exceeded"),
        }.get(v.rule_id, ("other", v.detail))
    return ("legal", "")
