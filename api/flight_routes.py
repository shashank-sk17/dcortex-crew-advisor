from datetime import datetime, date as date_type
from flask import Blueprint, jsonify, request

from .db import get_db_connection


flight_bp = Blueprint("flights", __name__)


@flight_bp.get("/api/v1/flights")
def get_flights():
    date_param = request.args.get("date")
    station = request.args.get("station")
    aircraft_filter = request.args.get("aircraft")
    status_filter = request.args.get("status")
    delay_rank_filter = request.args.get("delay_rank")

    allowed_status = {
        "on_time",
        "at_risk",
        "delayed",
        "cancelled"
    }

    allowed_delay_rank = {
        "critical",
        "high",
        "medium",
        "low"
    }

    try:
        if not date_param:
            return jsonify({
                "error": {
                    "code": "INVALID_DATE",
                    "message": "'date' is required and must be within 2026-09-14 … 2026-09-20."
                }
            }), 400

        try:
            requested_date = datetime.strptime(
                date_param,
                "%Y-%m-%d"
            ).date()
        except ValueError:
            return jsonify({
                "error": {
                    "code": "INVALID_DATE",
                    "message": "'date' is required and must be within 2026-09-14 … 2026-09-20."
                }
            }), 400

        if not (
            date_type(2026, 9, 14)
            <= requested_date
            <= date_type(2026, 9, 20)
        ):
            return jsonify({
                "error": {
                    "code": "INVALID_DATE",
                    "message": "'date' is required and must be within 2026-09-14 … 2026-09-20."
                }
            }), 400

        if status_filter and status_filter not in allowed_status:
            return jsonify({
                "error": {
                    "code": "INVALID_STATUS",
                    "message": "Invalid flight status"
                }
            }), 400

        if delay_rank_filter and delay_rank_filter not in allowed_delay_rank:
            return jsonify({
                "error": {
                    "code": "INVALID_DELAY_RANK",
                    "message": "Invalid delay rank"
                }
            }), 400

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                query = """
                    SELECT
                        f.flight_id,
                        f.flight_no,
                        f.date,
                        f.dep_station,
                        f.arr_station,
                        f.dep_utc,
                        f.arr_utc,
                        f.block_hours,
                        f.aircraft,
                        f.aircraft_type,
                        f.seats,
                        pdf.pairing_id
                    FROM flights f
                    LEFT JOIN pairing_day_flights pdf
                        ON pdf.flight_id = f.flight_id
                       AND pdf.date = f.date
                    WHERE f.date = %s
                """

                params = [requested_date]

                if station:
                    query += """
                        AND (
                            f.dep_station = %s
                            OR f.arr_station = %s
                        )
                    """
                    params.extend([station, station])

                if aircraft_filter:
                    query += " AND f.aircraft = %s "
                    params.append(aircraft_filter)

                query += """
                    ORDER BY f.dep_utc;
                """

                cur.execute(query, tuple(params))
                rows = cur.fetchall()

                flights = []

                for row in rows:

                    (
                        flight_id,
                        flight_no,
                        flight_date,
                        dep_station,
                        arr_station,
                        dep_utc,
                        arr_utc,
                        block_hours,
                        aircraft_value,
                        aircraft_type,
                        seats,
                        pairing_id
                    ) = row

                    # ---------------------------------------------
                    # Find all later legs operated by the same tail
                    # ---------------------------------------------
                    cur.execute("""
                        SELECT
                            f2.flight_id,
                            f2.dep_utc,
                            f2.arr_utc
                        FROM flights f2
                        WHERE f2.aircraft = %s
                          AND f2.dep_utc > %s
                        ORDER BY f2.dep_utc;
                    """, (
                        aircraft_value,
                        arr_utc
                    ))

                    downstream_rows = cur.fetchall()

                    downstream_count = len(downstream_rows)

                    # Next tail departure determines turnaround slack
                    slack_minutes = None

                    if downstream_rows:
                        next_dep = downstream_rows[0][1]

                        slack_minutes = int(
                            (
                                next_dep - arr_utc
                            ).total_seconds() / 60
                        )

                    # ---------------------------------------------
                    # FDP is intentionally NULL.
                    #
                    # duty_hours_7d cannot be used as FDP.
                    # ---------------------------------------------
                    crew_fdp_headroom_min = None

                    # ---------------------------------------------
                    # Rank signals that can be safely derived
                    # ---------------------------------------------
                    delay_reasons = []

                    if slack_minutes is not None:

                        if slack_minutes < 30:
                            delay_reasons.append(
                                "low aircraft turnaround slack"
                            )

                        elif slack_minutes < 60:
                            delay_reasons.append(
                                "reduced aircraft turnaround slack"
                            )

                    if downstream_count >= 4:
                        delay_reasons.append(
                            "high downstream aircraft impact"
                        )

                    # We cannot derive a reliable numeric score
                    # or full status from the current DB.
                    flight_status = None
                    flight_delay_rank = None
                    flight_delay_score = None

                    # Do not pretend filters are supported when the
                    # underlying value is unavailable.
                    if status_filter:
                        continue

                    if delay_rank_filter:
                        continue

                    flights.append({
                        "flight_id": flight_id,
                        "flight_no": flight_no,
                        "date": (
                            flight_date.isoformat()
                            if flight_date else None
                        ),
                        "dep_station": dep_station,
                        "arr_station": arr_station,
                        "dep_utc": (
                            dep_utc.isoformat()
                            if dep_utc else None
                        ),
                        "arr_utc": (
                            arr_utc.isoformat()
                            if arr_utc else None
                        ),
                        "block_hours": (
                            round(float(block_hours), 2)
                            if block_hours is not None
                            else None
                        ),
                        "aircraft": aircraft_value,
                        "aircraft_type": aircraft_type,
                        "seats": seats,
                        "pairing_id": pairing_id,
                        "status": flight_status,
                        "delay_rank": flight_delay_rank,
                        "delay_rank_score": flight_delay_score,
                        "delay_rank_reasons": delay_reasons,
                        "slack_minutes": slack_minutes,
                        "downstream_count": downstream_count,
                        "crew_fdp_headroom_min": crew_fdp_headroom_min,
                        "basis": [
                            "flights.json",
                            "rosters.json",
                            "rules.json"
                        ]
                    })

        return jsonify({
            "data": flights,
            "meta": {
                "count": len(flights)
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve flights"
            }
        }), 500


@flight_bp.get("/api/v1/flights/<flight_id>")
def get_flight(flight_id):

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # ---------------------------------------------
                # Flight
                # ---------------------------------------------
                cur.execute("""
                    SELECT
                        flight_id,
                        flight_no,
                        date,
                        dep_station,
                        arr_station,
                        dep_utc,
                        arr_utc,
                        block_hours,
                        aircraft,
                        aircraft_type,
                        seats
                    FROM flights
                    WHERE flight_id = %s;
                """, (flight_id,))

                flight = cur.fetchone()

                if flight is None:
                    return jsonify({
                        "error": {
                            "code": "FLIGHT_NOT_FOUND",
                            "message": "Flight not found"
                        }
                    }), 404

                (
                    flight_id,
                    flight_no,
                    flight_date,
                    dep_station,
                    arr_station,
                    dep_utc,
                    arr_utc,
                    block_hours,
                    aircraft,
                    aircraft_type,
                    seats
                ) = flight

                # ---------------------------------------------
                # Pairing
                # ---------------------------------------------
                cur.execute("""
                    SELECT pairing_id
                    FROM pairing_day_flights
                    WHERE flight_id = %s
                    LIMIT 1;
                """, (flight_id,))

                pairing_row = cur.fetchone()

                pairing_id = (
                    pairing_row[0]
                    if pairing_row
                    else None
                )

                # ---------------------------------------------
                # Crew
                # ---------------------------------------------
                crew = []

                if pairing_id:

                    cur.execute("""
                        SELECT
                            c.crew_id,
                            c.name,
                            pc.role,
                            c.rank
                        FROM pairing_crew pc
                        JOIN crew c
                            ON c.crew_id = pc.crew_id
                        WHERE pc.pairing_id = %s
                        ORDER BY pc.role, c.crew_id;
                    """, (pairing_id,))

                    crew_rows = cur.fetchall()

                    crew = [
                        {
                            "crew_id": r[0],
                            "name": r[1],
                            "role": r[2],
                            "rank": r[3]
                        }
                        for r in crew_rows
                    ]

                # ---------------------------------------------
                # Pairing day
                # ---------------------------------------------
                report_utc = None
                release_utc = None

                if pairing_id:

                    cur.execute("""
                        SELECT
                            report_utc,
                            release_utc
                        FROM pairing_days
                        WHERE pairing_id = %s
                          AND date = %s
                        LIMIT 1;
                    """, (
                        pairing_id,
                        flight_date
                    ))

                    day_row = cur.fetchone()

                    if day_row:
                        report_utc = day_row[0]
                        release_utc = day_row[1]

                # ---------------------------------------------
                # Previous leg in same pairing
                # ---------------------------------------------
                prev_leg = None

                if pairing_id:

                    cur.execute("""
                        SELECT f.flight_id
                        FROM pairing_day_flights pdf
                        JOIN flights f
                            ON f.flight_id = pdf.flight_id
                        WHERE pdf.pairing_id = %s
                          AND (
                              pdf.date < %s
                              OR (
                                  pdf.date = %s
                                  AND f.dep_utc < %s
                              )
                          )
                        ORDER BY f.dep_utc DESC
                        LIMIT 1;
                    """, (
                        pairing_id,
                        flight_date,
                        flight_date,
                        dep_utc
                    ))

                    prev_row = cur.fetchone()

                    if prev_row:
                        prev_leg = prev_row[0]

                # ---------------------------------------------
                # Next leg in same pairing
                # ---------------------------------------------
                next_leg = None

                if pairing_id:

                    cur.execute("""
                        SELECT f.flight_id
                        FROM pairing_day_flights pdf
                        JOIN flights f
                            ON f.flight_id = pdf.flight_id
                        WHERE pdf.pairing_id = %s
                          AND (
                              pdf.date > %s
                              OR (
                                  pdf.date = %s
                                  AND f.dep_utc > %s
                              )
                          )
                        ORDER BY f.dep_utc
                        LIMIT 1;
                    """, (
                        pairing_id,
                        flight_date,
                        flight_date,
                        dep_utc
                    ))

                    next_row = cur.fetchone()

                    if next_row:
                        next_leg = next_row[0]

                # ---------------------------------------------
                # Downstream tail legs
                # ---------------------------------------------
                cur.execute("""
                    SELECT
                        flight_id,
                        dep_utc,
                        arr_utc
                    FROM flights
                    WHERE aircraft = %s
                      AND dep_utc > %s
                    ORDER BY dep_utc;
                """, (
                    aircraft,
                    arr_utc
                ))

                downstream_rows = cur.fetchall()

                downstream_count = len(downstream_rows)

                slack_minutes = None

                if downstream_rows:

                    next_dep = downstream_rows[0][1]

                    slack_minutes = int(
                        (
                            next_dep - arr_utc
                        ).total_seconds() / 60
                    )

                # ---------------------------------------------
                # Operating crew pressure
                # ---------------------------------------------
                operating_crew_pressure = []

                for member in crew:

                    cur.execute("""
                        SELECT duty_hours_7d
                        FROM duty_clocks
                        WHERE crew_id = %s
                        ORDER BY as_of_utc DESC
                        LIMIT 1;
                    """, (member["crew_id"],))

                    duty_row = cur.fetchone()

                    if duty_row:

                        duty_hours = float(
                            duty_row[0] or 0
                        )

                        headroom = round(
                            60.0 - duty_hours,
                            2
                        )

                        operating_crew_pressure.append({
                            "crew_id": member["crew_id"],
                            "rule_id": "RULE-DUTY-02",
                            "headroom": headroom,
                            "status": (
                                "PASS"
                                if headroom >= 0
                                else "FAIL"
                            )
                        })

                # ---------------------------------------------
                # Safe derived signals
                # ---------------------------------------------
                delay_reasons = []

                if slack_minutes is not None:

                    if slack_minutes < 30:
                        delay_reasons.append(
                            "low aircraft turnaround slack"
                        )

                    elif slack_minutes < 60:
                        delay_reasons.append(
                            "reduced aircraft turnaround slack"
                        )

                if downstream_count >= 4:
                    delay_reasons.append(
                        "high downstream aircraft impact"
                    )

                return jsonify({
                    "data": {
                        "flight_id": flight_id,
                        "flight_no": flight_no,
                        "date": (
                            flight_date.isoformat()
                            if flight_date else None
                        ),
                        "dep_station": dep_station,
                        "arr_station": arr_station,
                        "dep_utc": (
                            dep_utc.isoformat()
                            if dep_utc else None
                        ),
                        "arr_utc": (
                            arr_utc.isoformat()
                            if arr_utc else None
                        ),
                        "block_hours": (
                            round(float(block_hours), 2)
                            if block_hours is not None
                            else None
                        ),
                        "aircraft": aircraft,
                        "aircraft_type": aircraft_type,
                        "seats": seats,
                        "pairing_id": pairing_id,

                        "status": None,
                        "delay_rank": None,
                        "delay_rank_score": None,

                        "delay_rank_reasons": delay_reasons,
                        "slack_minutes": slack_minutes,
                        "downstream_count": downstream_count,

                        "crew_fdp_headroom_min": None,

                        "crew": crew,

                        "report_utc": (
                            report_utc.isoformat()
                            if report_utc
                            else None
                        ),

                        "release_utc": (
                            release_utc.isoformat()
                            if release_utc
                            else None
                        ),

                        "pax_estimate": seats,
                        "prev_leg": prev_leg,
                        "next_leg": next_leg,

                        "operating_crew_pressure":
                            operating_crew_pressure,

                        "basis": [
                            "flights.json",
                            "rosters.json",
                            "duty_clocks.json",
                            "rules.json"
                        ]
                    }
                }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve flight"
            }
        }), 500

@flight_bp.get("/api/v1/flights/<flight_id>/downstream")
def get_flight_downstream(flight_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # 1. Check flight exists and get aircraft + arrival
                cur.execute("""
                    SELECT
                        flight_id,
                        aircraft,
                        arr_utc
                    FROM flights
                    WHERE flight_id = %s;
                """, (flight_id,))

                flight = cur.fetchone()

                if flight is None:
                    return jsonify({
                        "error": {
                            "code": "FLIGHT_NOT_FOUND",
                            "message": f"Flight '{flight_id}' not found"
                        }
                    }), 404

                aircraft = flight[1]
                arr_utc = flight[2]

                # 2. Get every later flight operated by the same aircraft
                cur.execute("""
                    SELECT
                        flight_id,
                        flight_no,
                        date,
                        dep_station,
                        arr_station,
                        dep_utc,
                        arr_utc,
                        block_hours,
                        aircraft,
                        aircraft_type,
                        seats
                    FROM flights
                    WHERE aircraft = %s
                      AND dep_utc > %s
                    ORDER BY dep_utc ASC;
                """, (aircraft, arr_utc))

                rows = cur.fetchall()

        data = []

        for row in rows:
            data.append({
                "flight_id": row[0],
                "flight_no": row[1],
                "date": row[2].isoformat() if row[2] is not None else None,
                "dep_station": row[3],
                "arr_station": row[4],
                "dep_utc": row[5].isoformat() if row[5] is not None else None,
                "arr_utc": row[6].isoformat() if row[6] is not None else None,
                "block_hours": float(row[7]) if row[7] is not None else None,
                "aircraft": row[8],
                "aircraft_type": row[9],
                "seats": row[10]
            })

        return jsonify({
            "data": data,
            "meta": {
                "count": len(data)
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve downstream flights"
            }
        }), 500