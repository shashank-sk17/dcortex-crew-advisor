"""Idempotent upserts into every Postgres table. Insert order respects FK
dependencies: crew and flights first, then everything that references them.

Every statement is INSERT ... ON CONFLICT ... DO UPDATE, so re-running the
pipeline against an unchanged dataset is a no-op in effect (safe to re-run
during development without truncating first).
"""
from __future__ import annotations

import psycopg

from . import transform_postgres as tp
from .loaders import Dataset


def _exec(conn: psycopg.Connection, sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def load_crew(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO crew (crew_id, name, rank, base, ratings, seniority, reachability_minutes, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (crew_id) DO UPDATE SET
            name = EXCLUDED.name, rank = EXCLUDED.rank, base = EXCLUDED.base,
            ratings = EXCLUDED.ratings, seniority = EXCLUDED.seniority,
            reachability_minutes = EXCLUDED.reachability_minutes, status = EXCLUDED.status
    """
    return _exec(conn, sql, tp.crew_rows(ds))


def load_flights(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO flights (flight_id, flight_no, date, dep_station, arr_station,
                              dep_utc, arr_utc, block_hours, aircraft, aircraft_type, seats)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (flight_id) DO UPDATE SET
            flight_no = EXCLUDED.flight_no, date = EXCLUDED.date,
            dep_station = EXCLUDED.dep_station, arr_station = EXCLUDED.arr_station,
            dep_utc = EXCLUDED.dep_utc, arr_utc = EXCLUDED.arr_utc,
            block_hours = EXCLUDED.block_hours, aircraft = EXCLUDED.aircraft,
            aircraft_type = EXCLUDED.aircraft_type, seats = EXCLUDED.seats
    """
    return _exec(conn, sql, tp.flight_rows(ds))


def load_certifications(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO certifications (crew_id, cert_type, valid_from, valid_to)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (crew_id, cert_type) DO UPDATE SET
            valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to
    """
    return _exec(conn, sql, tp.certification_rows(ds))


def load_duty_clocks(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO duty_clocks (crew_id, as_of_utc, duty_hours_7d, flight_hours_28d, last_rest_ended)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (crew_id) DO UPDATE SET
            as_of_utc = EXCLUDED.as_of_utc, duty_hours_7d = EXCLUDED.duty_hours_7d,
            flight_hours_28d = EXCLUDED.flight_hours_28d, last_rest_ended = EXCLUDED.last_rest_ended
    """
    return _exec(conn, sql, tp.duty_clock_rows(ds))


def load_duty_daily_history(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO duty_daily_history (crew_id, date, duty_hours, flight_hours)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (crew_id, date) DO UPDATE SET
            duty_hours = EXCLUDED.duty_hours, flight_hours = EXCLUDED.flight_hours
    """
    return _exec(conn, sql, tp.duty_daily_history_rows(ds))


def load_reserve_pool(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO reserve_pool (crew_id, base, dates, oncall_start_utc, oncall_end_utc)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (crew_id) DO UPDATE SET
            base = EXCLUDED.base, dates = EXCLUDED.dates,
            oncall_start_utc = EXCLUDED.oncall_start_utc, oncall_end_utc = EXCLUDED.oncall_end_utc
    """
    return _exec(conn, sql, tp.reserve_pool_rows(ds))


def load_pairings(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO pairings (pairing_id, aircraft)
        VALUES (%s, %s)
        ON CONFLICT (pairing_id) DO UPDATE SET aircraft = EXCLUDED.aircraft
    """
    return _exec(conn, sql, tp.pairing_rows(ds))


def load_pairing_days(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO pairing_days (pairing_id, date, report_utc, release_utc)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (pairing_id, date) DO UPDATE SET
            report_utc = EXCLUDED.report_utc, release_utc = EXCLUDED.release_utc
    """
    return _exec(conn, sql, tp.pairing_day_rows(ds))


def load_pairing_day_flights(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO pairing_day_flights (pairing_id, date, flight_id, leg_order)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (pairing_id, date, flight_id) DO UPDATE SET leg_order = EXCLUDED.leg_order
    """
    return _exec(conn, sql, tp.pairing_day_flight_rows(ds))


def load_pairing_crew(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO pairing_crew (pairing_id, crew_id, role)
        VALUES (%s, %s, %s)
        ON CONFLICT (pairing_id, crew_id) DO UPDATE SET role = EXCLUDED.role
    """
    return _exec(conn, sql, tp.pairing_crew_rows(ds))


def load_roster_exceptions(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO roster_exceptions (crew_id, date, rule, note)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (crew_id, date, rule) DO UPDATE SET note = EXCLUDED.note
    """
    return _exec(conn, sql, tp.roster_exception_rows(ds))


def load_costs(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO costs (id, currency, reserve_callout_pilot, reserve_callout_cabin,
                            dayoff_callout_pilot, dayoff_callout_cabin, deadhead_positioning,
                            delay_cost_per_duty_hour, cancellation_per_flight, hotel_overnight)
        VALUES (TRUE, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            currency = EXCLUDED.currency,
            reserve_callout_pilot = EXCLUDED.reserve_callout_pilot,
            reserve_callout_cabin = EXCLUDED.reserve_callout_cabin,
            dayoff_callout_pilot = EXCLUDED.dayoff_callout_pilot,
            dayoff_callout_cabin = EXCLUDED.dayoff_callout_cabin,
            deadhead_positioning = EXCLUDED.deadhead_positioning,
            delay_cost_per_duty_hour = EXCLUDED.delay_cost_per_duty_hour,
            cancellation_per_flight = EXCLUDED.cancellation_per_flight,
            hotel_overnight = EXCLUDED.hotel_overnight
    """
    return _exec(conn, sql, [tp.costs_row(ds)])


def load_risk_signals(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO risk_signals (crew_id, as_of_utc, disruption_risk_score, drivers)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (crew_id) DO UPDATE SET
            as_of_utc = EXCLUDED.as_of_utc, disruption_risk_score = EXCLUDED.disruption_risk_score,
            drivers = EXCLUDED.drivers
    """
    return _exec(conn, sql, tp.risk_signal_rows(ds))


def load_boarding_gates(conn: psycopg.Connection, ds: Dataset) -> int:
    sql = """
        INSERT INTO boarding_gates (flight_id, boarding_gate_number, pairing_id,
                                     date, boarding_start_time, boarding_end_time,
                                     aircraft_type)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (flight_id) DO UPDATE SET
            boarding_gate_number = EXCLUDED.boarding_gate_number,
            pairing_id = EXCLUDED.pairing_id, date = EXCLUDED.date,
            boarding_start_time = EXCLUDED.boarding_start_time,
            boarding_end_time = EXCLUDED.boarding_end_time,
            aircraft_type = EXCLUDED.aircraft_type
    """
    return _exec(conn, sql, tp.boarding_gate_rows(ds))


def load_all(conn: psycopg.Connection, ds: Dataset) -> dict[str, int]:
    """FK-respecting order: crew and flights and pairings first, then rows
    that reference them."""
    counts: dict[str, int] = {}
    counts["crew"] = load_crew(conn, ds)
    counts["flights"] = load_flights(conn, ds)
    counts["pairings"] = load_pairings(conn, ds)
    counts["certifications"] = load_certifications(conn, ds)
    counts["duty_clocks"] = load_duty_clocks(conn, ds)
    counts["duty_daily_history"] = load_duty_daily_history(conn, ds)
    counts["reserve_pool"] = load_reserve_pool(conn, ds)
    counts["pairing_days"] = load_pairing_days(conn, ds)
    counts["pairing_day_flights"] = load_pairing_day_flights(conn, ds)
    counts["pairing_crew"] = load_pairing_crew(conn, ds)
    counts["roster_exceptions"] = load_roster_exceptions(conn, ds)
    counts["costs"] = load_costs(conn, ds)
    counts["risk_signals"] = load_risk_signals(conn, ds)
    counts["boarding_gates"] = load_boarding_gates(conn, ds)
    conn.commit()
    return counts
