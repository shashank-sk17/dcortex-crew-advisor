#!/usr/bin/env python3
"""Generates mock_data/boarding_gate.json — fabricated gate assignments laid
over the REAL flight schedule. This is mock/fabricated data (dCortex's own
dataset has no gate information at all — confirmed by grepping the whole
vendored dataset), kept separate from crew-ops-advisor-dataset/, which is
vendored and never edited.

Only the gate NUMBER is invented. Everything else — pairing_id, flight_id,
date, aircraft_type, and the gate-occupancy window itself — is computed from
the real vendored data, chained per tail across the whole week so turnarounds
connect correctly (verified: every tail's route is fully continuous, zero
station gaps, across all 147 flights).

Turnaround buffer (how long a gate is held before an aircraft's own
departure, when it isn't a direct continuation of its own prior leg) is
aircraft-type based, grounded in published domestic short-haul norms.
Everything in this dataset is domestic (8 Indian stations, no long-haul), so:

    A320  (162 seats) -> 45 min  ("Legacy Domestic" tier: 45-60 min)
    ATR72 (72 seats)  -> 30 min  (fewer pax/bags -> faster turn,
                                   "Low-Cost Domestic" tier: 25-45 min)

A flight with no prior leg at all for its tail (the very first flight of the
whole week) uses an 8h overnight/originating buffer (published "Overnight/
Originating" tier: 6-10h). A flight that IS a continuation of its own tail's
previous leg (arr_station of leg N == dep_station of leg N+1) instead starts
its gate window at that previous leg's real arrival time — this is usually
much longer than the fixed buffer (e.g. P-2291's DEL overnight is ~14h, not
the flat 8h default) and is the actually-correct figure for that specific
rotation, not a guess.

Gate NUMBERS are assigned per station via interval partitioning (the same
algorithm as "minimum meeting rooms needed"): sorted by boarding_start_time,
a flight reuses the earliest gate that's already free, or gets a new one.
This guarantees no two flights with overlapping windows at the same station
are ever assigned the same gate — a real physical constraint, not just
cosmetic.

NOTE: this window is departure-side only (boarding_end_time is always this
flight's own dep_utc). There is no separate arrival/deplaning record; the
arrival side only ever shows up implicitly, as the next continuing leg's
boarding_start_time. Despite the field names, this is the full gate-turnaround
window (aircraft on stand), not the narrower passenger-boarding call window
real airlines use (~20-30 min pre-departure) — see mock_data/README.md.

Run: python3 mock_data/generate_boarding_gates.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "crew-ops-advisor-dataset" / "data"
OUT_PATH = Path(__file__).resolve().parent / "boarding_gate.json"

TURNAROUND_MIN = {"A320": 45, "ATR72": 30}
DEFAULT_TURNAROUND_MIN = 45
OVERNIGHT_HOURS = 8

FMT = "%Y-%m-%dT%H:%M:%SZ"


def load(name: str):
    with open(DATA_DIR / name, encoding="utf-8") as fh:
        return json.load(fh)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT)


def iso(dt: datetime) -> str:
    return dt.strftime(FMT)


def build_flight_to_pairing(rosters: dict) -> dict[str, str]:
    """flight_id -> pairing_id. Not present on flights.json itself; only
    derivable by walking rosters.json's pairings[].days[].flights[]."""
    mapping: dict[str, str] = {}
    for pairing in rosters["pairings"]:
        for day in pairing["days"]:
            for flight_id in day["flights"]:
                mapping[flight_id] = pairing["pairing_id"]
    return mapping


def compute_gate_windows(flights: list[dict], flight_to_pairing: dict[str, str]) -> list[dict]:
    by_tail: dict[str, list[dict]] = {}
    for f in flights:
        by_tail.setdefault(f["aircraft"], []).append(f)

    records = []
    for tail, legs in by_tail.items():
        legs.sort(key=lambda f: f["dep_utc"])
        prev_arr: datetime | None = None
        prev_arr_station: str | None = None
        for f in legs:
            dep = parse(f["dep_utc"])
            if prev_arr is not None and prev_arr_station == f["dep_station"]:
                start = prev_arr  # continuing rotation: real prior arrival, not a guess
            elif prev_arr is None:
                start = dep - timedelta(hours=OVERNIGHT_HOURS)  # first flight of the week for this tail
            else:
                buffer_min = TURNAROUND_MIN.get(f["aircraft_type"], DEFAULT_TURNAROUND_MIN)
                start = dep - timedelta(minutes=buffer_min)

            records.append({
                "pairing_id": flight_to_pairing.get(f["flight_id"]),
                "flight_id": f["flight_id"],
                "date": f["date"],
                "dep_station": f["dep_station"],
                "boarding_start_time": iso(start),
                "boarding_end_time": f["dep_utc"],
                "aircraft_type": f["aircraft_type"],
            })
            prev_arr = parse(f["arr_utc"])
            prev_arr_station = f["arr_station"]
    return records


def assign_gate_numbers(records: list[dict]) -> None:
    """Interval partitioning per station -- mutates records in place, adding
    `boarding_gate_number`. No two overlapping-window flights at the same
    station ever share a gate."""
    by_station: dict[str, list[dict]] = {}
    for r in records:
        by_station.setdefault(r["dep_station"], []).append(r)

    for station, recs in by_station.items():
        recs.sort(key=lambda r: parse(r["boarding_start_time"]))
        gate_free_at: list[datetime] = []
        for r in recs:
            start, end = parse(r["boarding_start_time"]), parse(r["boarding_end_time"])
            assigned = next((i for i, free_at in enumerate(gate_free_at) if free_at <= start), None)
            if assigned is None:
                assigned = len(gate_free_at)
                gate_free_at.append(end)
            else:
                gate_free_at[assigned] = end
            r["boarding_gate_number"] = f"{station}-G{assigned + 1}"


def main() -> None:
    flights = load("flights.json")
    rosters = load("rosters.json")
    flight_to_pairing = build_flight_to_pairing(rosters)

    records = compute_gate_windows(flights, flight_to_pairing)
    unmatched = [r["flight_id"] for r in records if r["pairing_id"] is None]
    assign_gate_numbers(records)

    out = [
        {
            "boarding_gate_number": r["boarding_gate_number"],
            "pairing_id": r["pairing_id"],
            "flight_id": r["flight_id"],
            "date": r["date"],
            "boarding_start_time": r["boarding_start_time"],
            "boarding_end_time": r["boarding_end_time"],
            "aircraft_type": r["aircraft_type"],
        }
        for r in records
    ]
    out.sort(key=lambda r: r["flight_id"])

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)

    print(f"Wrote {len(out)} records to {OUT_PATH}")
    if unmatched:
        print(f"WARNING: {len(unmatched)} flights had no pairing match: {unmatched}")


if __name__ == "__main__":
    main()
