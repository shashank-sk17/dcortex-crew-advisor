from __future__ import annotations

from .loaders import Dataset


def crew_rows(ds: Dataset) -> list[tuple]:
    return [
        (
            c["crew_id"],
            c["name"],
            c["rank"],
            c["base"],
            c["ratings"],
            c["seniority"],
            c["reachability_minutes"],
            c["status"],
        )
        for c in ds.crew
    ]


def flight_rows(ds: Dataset) -> list[tuple]:
    return [
        (
            f["flight_id"],
            f["flight_no"],
            f["date"],
            f["dep_station"],
            f["arr_station"],
            f["dep_utc"],
            f["arr_utc"],
            f["block_hours"],
            f["aircraft"],
            f["aircraft_type"],
            f["seats"],
        )
        for f in ds.flights
    ]


def certification_rows(ds: Dataset) -> list[tuple]:
    return [
        (c["crew_id"], c["cert_type"], c["valid_from"], c["valid_to"])
        for c in ds.certifications
    ]


def duty_clock_rows(ds: Dataset) -> list[tuple]:
    return [
        (
            dc["crew_id"],
            dc["as_of_utc"],
            dc["duty_hours_7d"],
            dc["flight_hours_28d"],
            dc["last_rest_ended"],
        )
        for dc in ds.duty_clocks
    ]


def duty_daily_history_rows(ds: Dataset) -> list[tuple]:
    rows = []
    for dc in ds.duty_clocks:
        crew_id = dc["crew_id"]
        for day in dc["daily_history"]:
            rows.append((crew_id, day["date"], day["duty_hours"], day["flight_hours"]))
    return rows


def reserve_pool_rows(ds: Dataset) -> list[tuple]:
    return [
        (
            r["crew_id"],
            r["base"],
            r["dates"],
            r["oncall_window_utc"]["start"],
            r["oncall_window_utc"]["end"],
        )
        for r in ds.reserve_pool
    ]


def pairing_rows(ds: Dataset) -> list[tuple]:
    return [(p["pairing_id"], p["aircraft"]) for p in ds.rosters["pairings"]]


def pairing_day_rows(ds: Dataset) -> list[tuple]:
    rows = []
    for p in ds.rosters["pairings"]:
        for day in p["days"]:
            rows.append((p["pairing_id"], day["date"], day["report_utc"], day["release_utc"]))
    return rows


def pairing_day_flight_rows(ds: Dataset) -> list[tuple]:
    rows = []
    for p in ds.rosters["pairings"]:
        for day in p["days"]:
            for order, flight_id in enumerate(day["flights"]):
                rows.append((p["pairing_id"], day["date"], flight_id, order))
    return rows


def pairing_crew_rows(ds: Dataset) -> list[tuple]:
    rows = []
    for p in ds.rosters["pairings"]:
        for member in p["crew"]:
            rows.append((p["pairing_id"], member["crew_id"], member["role"]))
    return rows


def roster_exception_rows(ds: Dataset) -> list[tuple]:
    return [
        (e["crew_id"], e["date"], e["rule"], e["note"])
        for e in ds.rosters["flagged_exceptions"]
    ]


def costs_row(ds: Dataset) -> tuple:
    c = ds.costs
    return (
        c["currency"],
        c["reserve_callout_pilot"],
        c["reserve_callout_cabin"],
        c["dayoff_callout_pilot"],
        c["dayoff_callout_cabin"],
        c["deadhead_positioning"],
        c["delay_cost_per_duty_hour"],
        c["cancellation_per_flight"],
        c["hotel_overnight"],
    )


def risk_signal_rows(ds: Dataset) -> list[tuple]:
    return [
        (r["crew_id"], r["as_of_utc"], r["disruption_risk_score"], r["drivers"])
        for r in ds.risk_signals
    ]
