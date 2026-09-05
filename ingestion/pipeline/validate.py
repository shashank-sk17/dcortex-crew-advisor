"""Post-ingestion row-count validation. Expected counts are derived from the
in-memory dataset, never hardcoded -- so this stays correct if the vendored
dataset is ever regenerated at a different size.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from .loaders import Dataset


@dataclass
class CheckResult:
    table: str
    expected: int
    actual: int

    @property
    def ok(self) -> bool:
        return self.expected == self.actual


def _count(conn: psycopg.Connection, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # nosec: table names are fixed constants below, never user input
        return cur.fetchone()[0]


def expected_counts(ds: Dataset) -> dict[str, int]:
    pairings = ds.rosters["pairings"]
    return {
        "crew": len(ds.crew),
        "flights": len(ds.flights),
        "certifications": len(ds.certifications),
        "duty_clocks": len(ds.duty_clocks),
        "duty_daily_history": sum(len(dc["daily_history"]) for dc in ds.duty_clocks),
        "reserve_pool": len(ds.reserve_pool),
        "pairings": len(pairings),
        "pairing_days": sum(len(p["days"]) for p in pairings),
        "pairing_day_flights": sum(len(day["flights"]) for p in pairings for day in p["days"]),
        "pairing_crew": sum(len(p["crew"]) for p in pairings),
        "roster_exceptions": len(ds.rosters["flagged_exceptions"]),
        "costs": 1,
        "risk_signals": len(ds.risk_signals),
        "boarding_gates": len(ds.boarding_gates),
        "rules_vec": len(ds.rules["rules"]),
        "scenario_precedent_vec": len(ds.scenarios),
        "controller_note_vec": len(ds.rosters["flagged_exceptions"]),
        "intent_example_vec": len(ds.questions),
    }


def validate(conn: psycopg.Connection, ds: Dataset) -> list[CheckResult]:
    results = []
    for table, expected in expected_counts(ds).items():
        results.append(CheckResult(table=table, expected=expected, actual=_count(conn, table)))
    return results
