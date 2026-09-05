from flask import Blueprint, jsonify, request
from datetime import datetime

from .db import get_db_connection


crew_bp = Blueprint("crew", __name__)

@crew_bp.get("/api/v1/crew")
def get_crew():
    date = request.args.get("date")
    crew_filter = request.args.get("filter", "all")
    role = request.args.get("role")
    base = request.args.get("base")
    status = request.args.get("status")
    q = request.args.get("q")

    valid_filters = {
        "needs_attention",
        "on_duty",
        "off_duty",
        "on_reserve",
        "all"
    }

    if crew_filter not in valid_filters:
        return jsonify({
            "error": {
                "code": "INVALID_FILTER",
                "message": "Invalid crew filter"
            }
        }), 400

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # 1. Get crew
                query = """
                    SELECT
                        crew_id,
                        name,
                        rank,
                        base,
                        ratings,
                        seniority,
                        reachability_minutes,
                        status
                    FROM crew
                    WHERE 1=1
                """

                params = []

                if role:
                    query += " AND LOWER(rank) = LOWER(%s)"
                    params.append(role)

                if base:
                    query += " AND base = %s"
                    params.append(base)

                if status:
                    query += " AND status = %s"
                    params.append(status)

                if q:
                    query += """
                        AND (
                            crew_id ILIKE %s
                            OR name ILIKE %s
                        )
                    """
                    params.extend([f"%{q}%", f"%{q}%"])

                query += " ORDER BY crew_id"

                cur.execute(query, params)
                crew_rows = cur.fetchall()

                # 2. Get assignments for requested date
                assignment_map = {}

                if date:
                    cur.execute("""
                        SELECT
                            pc.crew_id,
                            pc.pairing_id,
                            pc.role,
                            pdf.flight_id,
                            pd.report_utc
                        FROM pairing_crew pc
                        JOIN pairing_days pd
                            ON pd.pairing_id = pc.pairing_id
                        LEFT JOIN pairing_day_flights pdf
                            ON pdf.pairing_id = pc.pairing_id
                           AND pdf.date = pd.date
                           AND pdf.leg_order = 1
                        WHERE pd.date = %s
                        ORDER BY pd.report_utc
                    """, (date,))

                    for row in cur.fetchall():
                        crew_id = row[0]

                        if crew_id not in assignment_map:
                            assignment_map[crew_id] = {
                                "pairing_id": row[1],
                                "role": row[2],
                                "flight_id": row[3],
                                "report_utc": row[4]
                            }

                # 3. Get latest duty clock
                cur.execute("""
                    SELECT DISTINCT ON (crew_id)
                        crew_id,
                        duty_hours_7d
                    FROM duty_clocks
                    ORDER BY crew_id, as_of_utc DESC
                """)

                duty_map = {
                    row[0]: row[1]
                    for row in cur.fetchall()
                }

                # 4. Get latest risk
                cur.execute("""
                    SELECT DISTINCT ON (crew_id)
                        crew_id,
                        disruption_risk_score
                    FROM risk_signals
                    ORDER BY crew_id, as_of_utc DESC
                """)

                risk_map = {
                    row[0]: row[1]
                    for row in cur.fetchall()
                }

        # 5. Build response
        crew = []

        for row in crew_rows:
            (
                crew_id,
                name,
                rank,
                base_value,
                ratings,
                seniority,
                reachability_minutes,
                crew_status
            ) = row

            assignment = assignment_map.get(crew_id)

            duty_value = duty_map.get(crew_id)

            duty_7d = (
                round(float(duty_value), 2)
                if duty_value is not None
                else None
            )

            duty_7d_headroom = (
                round(60.0 - duty_7d, 2)
                if duty_7d is not None
                else None
            )

            risk_value = risk_map.get(crew_id)

            disruption_risk_score = (
                round(float(risk_value), 2)
                if risk_value is not None
                else None
            )

            on_duty = assignment is not None

            reasons = []

            if (
                duty_7d_headroom is not None
                and duty_7d_headroom < 3
            ):
                reasons.append(
                    f"RULE-DUTY-02 headroom "
                    f"{duty_7d_headroom:g}h < 3h"
                )

            if (
                disruption_risk_score is not None
                and disruption_risk_score >= 0.7
            ):
                reasons.append(
                    "Disruption risk score is high"
                )

            # Filters
            if crew_filter == "needs_attention" and not reasons:
                continue

            if crew_filter == "on_duty" and not on_duty:
                continue

            if crew_filter == "off_duty" and on_duty:
                continue

            if crew_filter == "on_reserve":
                if str(crew_status).lower() != "reserve":
                    continue

            crew.append({
                "crew_id": crew_id,
                "name": name,
                "rank": rank,
                "base": base_value,
                "ratings": ratings,
                "seniority": seniority,
                "reachability_minutes": reachability_minutes,
                "status": crew_status,

                "on_duty": on_duty,

                "current_assignment": {
                    "pairing_id": (
                        assignment["pairing_id"]
                        if assignment else None
                    ),
                    "flight_id": (
                        assignment["flight_id"]
                        if assignment else None
                    )
                },

                "next_report_utc": (
                    assignment["report_utc"].isoformat()
                    if assignment
                    and assignment["report_utc"] is not None
                    else None
                ),

                "duty_7d": duty_7d,
                "duty_7d_headroom": duty_7d_headroom,

                "disruption_risk_score": disruption_risk_score,

                "attention": {
                    "flag": len(reasons) > 0,
                    "reasons": reasons
                },

            })

        return jsonify({
            "data": crew,
            "meta": {
                "count": len(crew)
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve crew"
            }
        }), 500
    
@crew_bp.get("/api/v1/crew/<crew_id>")
def get_crew_member(crew_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        crew_id,
                        name,
                        rank,
                        base,
                        ratings,
                        seniority,
                        reachability_minutes,
                        status
                    FROM crew
                    WHERE crew_id = %s;
                """, (crew_id,))

                row = cur.fetchone()

        if row is None:
            return jsonify({
                "error": {
                    "code": "CREW_NOT_FOUND",
                    "message": f"Crew member '{crew_id}' not found"
                }
            }), 404

        return jsonify({
            "data": {
                "crew_id": row[0],
                "name": row[1],
                "rank": row[2],
                "base": row[3],
                "ratings": row[4],
                "seniority": row[5],
                "reachability_minutes": row[6],
                "status": row[7]
            }
        }), 200

    except Exception as e:
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": str(e)
            }
        }), 500

@crew_bp.get("/api/v1/crew/<crew_id>/duty-clock")
def get_crew_duty_clock(crew_id):
    try:
        date_param = request.args.get("date")

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # Check crew exists
                cur.execute("""
                    SELECT crew_id
                    FROM crew
                    WHERE crew_id = %s;
                """, (crew_id,))

                if cur.fetchone() is None:
                    return jsonify({
                        "error": {
                            "code": "CREW_NOT_FOUND",
                            "message": f"Crew member '{crew_id}' not found"
                        }
                    }), 404

                # Get latest duty-clock snapshot
                cur.execute("""
                    SELECT
                        crew_id,
                        as_of_utc,
                        duty_hours_7d,
                        flight_hours_28d,
                        last_rest_ended
                    FROM duty_clocks
                    WHERE crew_id = %s
                    ORDER BY as_of_utc DESC
                    LIMIT 1;
                """, (crew_id,))

                row = cur.fetchone()

        if row is None:
            return jsonify({
                "error": {
                    "code": "DUTY_CLOCK_NOT_FOUND",
                    "message": "Duty clock not found"
                }
            }), 404

        duty_hours = float(row[2]) if row[2] is not None else 0.0
        flight_hours = float(row[3]) if row[3] is not None else 0.0

        duty_headroom = 60.0 - duty_hours
        flight_headroom = 100.0 - flight_hours

        # We only have last_rest_ended in duty_clocks.
        # Do not invent a rest rule here.
        rest_ok = row[4] is not None

        response_date = date_param

        if response_date is None and row[1] is not None:
            response_date = row[1].date().isoformat()

        return jsonify({
            "data": {
                "crew_id": row[0],
                "date": response_date,
                "as_of_utc": (
                    row[1].isoformat()
                    if row[1] is not None
                    else None
                ),
                "duty_hours_7d": round(duty_hours, 2),
                "duty_7d_headroom": round(duty_headroom, 2),
                "flight_hours_28d": round(flight_hours, 2),
                "flight_28d_headroom": round(flight_headroom, 2),
                "last_rest_ended": (
                    row[4].isoformat()
                    if row[4] is not None
                    else None
                ),
                "rest_ok": rest_ok
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve duty clock"
            }
        }), 500

@crew_bp.get("/api/v1/crew/<crew_id>/certifications")
def get_crew_certifications(crew_id):
    try:
        on_param = request.args.get("on")

        # Validate ?on=
        if on_param:
            try:
                on_date = datetime.strptime(
                    on_param, "%Y-%m-%d"
                ).date()
            except ValueError:
                return jsonify({
                    "error": {
                        "code": "INVALID_DATE",
                        "message": "Invalid date format. Use YYYY-MM-DD"
                    }
                }), 400
        else:
            on_date = None

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # Check crew exists
                cur.execute(
                    "SELECT crew_id FROM crew WHERE crew_id = %s",
                    (crew_id,)
                )

                if cur.fetchone() is None:
                    return jsonify({
                        "error": {
                            "code": "CREW_NOT_FOUND",
                            "message": "Crew member not found"
                        }
                    }), 404

                # Fetch certifications
                cur.execute("""
                    SELECT
                        crew_id,
                        cert_type,
                        valid_from,
                        valid_to
                    FROM certifications
                    WHERE crew_id = %s
                    ORDER BY valid_to
                """, (crew_id,))

                rows = cur.fetchall()

        def to_date(value):
            if value is None:
                return None

            if isinstance(value, datetime):
                return value.date()

            if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
                return value

            if isinstance(value, str):
                return datetime.fromisoformat(
                    value.replace("Z", "+00:00")
                ).date()

            return None

        data = []

        for row in rows:
            valid_from = to_date(row[2])
            valid_to = to_date(row[3])

            # If ?on is supplied, evaluate against that date.
            # Otherwise use valid_from as the fallback.
            evaluation_date = on_date or valid_from

            if valid_to and evaluation_date:
                days_to_expiry = (valid_to - evaluation_date).days
                # Don't include expired certifications
                if days_to_expiry < 0:
                    continue
            else:
                days_to_expiry = None

            # Match the API example:
            # expired (-2 days) => expiring_soon = false
            expiring_soon = (
                days_to_expiry is not None
                and 0 <= days_to_expiry <= 3
            )

            data.append({
                "crew_id": row[0],
                "cert_type": row[1],
                "valid_from": (
                    valid_from.isoformat()
                    if valid_from else None
                ),
                "valid_to": (
                    valid_to.isoformat()
                    if valid_to else None
                ),
                "days_to_expiry": days_to_expiry,
                "expiring_soon": expiring_soon
            })

        return jsonify({
            "data": data,
            "meta": {
                "count": len(data)
            }
        }), 200

    except Exception as e:
        print("CERTIFICATIONS ERROR:", repr(e))

        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve certifications"
            }
        }), 500
    
@crew_bp.get("/api/v1/crew/<crew_id>/exceptions")
def get_crew_exceptions(crew_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # Check that crew member exists
                cur.execute("""
                    SELECT crew_id
                    FROM crew
                    WHERE crew_id = %s;
                """, (crew_id,))

                crew = cur.fetchone()

                if crew is None:
                    return jsonify({
                        "error": {
                            "code": "CREW_NOT_FOUND",
                            "message": f"Crew member '{crew_id}' not found"
                        }
                    }), 404

                cur.execute("""
                    SELECT
                        crew_id,
                        date,
                        rule,
                        note
                    FROM roster_exceptions
                    WHERE crew_id = %s
                    ORDER BY date;
                """, (crew_id,))

                rows = cur.fetchall()

        exceptions = [
            {
                "crew_id": row[0],
                "date": row[1],
                "rule": row[2],
                "note": row[3]
            }
            for row in rows
        ]

        return jsonify({
            "data": exceptions
        }), 200

    except Exception as e:
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": str(e)
            }
        }), 500
    
@crew_bp.get("/api/v1/crew/<crew_id>/risk")
def get_crew_risk(crew_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # Check that crew member exists
                cur.execute("""
                    SELECT crew_id
                    FROM crew
                    WHERE crew_id = %s;
                """, (crew_id,))

                crew = cur.fetchone()

                if crew is None:
                    return jsonify({
                        "error": {
                            "code": "CREW_NOT_FOUND",
                            "message": f"Crew member '{crew_id}' not found"
                        }
                    }), 404

                # Get latest risk signal
                cur.execute("""
                    SELECT
                        crew_id,
                        as_of_utc,
                        disruption_risk_score,
                        drivers
                    FROM risk_signals
                    WHERE crew_id = %s
                    ORDER BY as_of_utc DESC
                    LIMIT 1;
                """, (crew_id,))

                row = cur.fetchone()

        if row is None:
            return jsonify({
                "error": {
                    "code": "RISK_NOT_FOUND",
                    "message": f"No risk signal found for crew member '{crew_id}'"
                }
            }), 404

        return jsonify({
            "data": {
                "crew_id": row[0],
                "as_of_utc": row[1],
                "disruption_risk_score": row[2],
                "drivers": row[3]
            }
        }), 200

    except Exception as e:
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": str(e)
            }
        }), 500
@crew_bp.get("/api/v1/crew/<crew_id>/legality")
def check_crew_legality(crew_id):
    try:
        pairing_id = request.args.get("pairing_id")
        delay_h_raw = request.args.get("delay_h", "0")

        # ---------------------------------------------------------
        # Validate request parameters
        # ---------------------------------------------------------
        if not pairing_id:
            return jsonify({
                "error": {
                    "code": "MISSING_PARAMETER",
                    "message": "pairing_id is required"
                }
            }), 400

        try:
            delay_h = float(delay_h_raw)
        except (TypeError, ValueError):
            return jsonify({
                "error": {
                    "code": "INVALID_PARAMETER",
                    "message": "delay_h must be a number"
                }
            }), 400

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # -------------------------------------------------
                # Get crew
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        crew_id,
                        name,
                        rank,
                        base,
                        ratings,
                        seniority,
                        reachability_minutes,
                        status
                    FROM crew
                    WHERE crew_id = %s;
                """, (crew_id,))

                crew = cur.fetchone()

                if crew is None:
                    return jsonify({
                        "error": {
                            "code": "CREW_NOT_FOUND",
                            "message": f"Crew member '{crew_id}' not found"
                        }
                    }), 404

                crew_base = crew[3]
                crew_ratings = crew[4] or []

                # -------------------------------------------------
                # Check pairing exists
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        pairing_id,
                        aircraft
                    FROM pairings
                    WHERE pairing_id = %s;
                """, (pairing_id,))

                pairing = cur.fetchone()

                if pairing is None:
                    return jsonify({
                        "error": {
                            "code": "PAIRING_NOT_FOUND",
                            "message": "Pairing not found"
                        }
                    }), 404

                # -------------------------------------------------
                # Get pairing days
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        date,
                        report_utc,
                        release_utc
                    FROM pairing_days
                    WHERE pairing_id = %s
                    ORDER BY date;
                """, (pairing_id,))

                pairing_days = cur.fetchall()

                if not pairing_days:
                    return jsonify({
                        "error": {
                            "code": "PAIRING_NOT_FOUND",
                            "message": "Pairing not found"
                        }
                    }), 404

                # -------------------------------------------------
                # Get flights belonging to the pairing
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        pdf.date,
                        pdf.leg_order,
                        f.flight_id,
                        f.flight_no,
                        f.dep_station,
                        f.arr_station,
                        f.dep_utc,
                        f.arr_utc,
                        f.block_hours,
                        f.aircraft_type
                    FROM pairing_day_flights pdf
                    JOIN flights f
                        ON f.flight_id = pdf.flight_id
                    WHERE pdf.pairing_id = %s
                    ORDER BY pdf.date, pdf.leg_order;
                """, (pairing_id,))

                flights = cur.fetchall()

                # -------------------------------------------------
                # Evaluation date
                # The legality response is based on the first
                # duty date of the pairing.
                # -------------------------------------------------
                legality_date = pairing_days[0][0]
                report_utc = pairing_days[0][1]
                release_utc = pairing_days[0][2]

                # -------------------------------------------------
                # Pairing duty duration
                # -------------------------------------------------
                duty_hours = 0.0

                for day in pairing_days:
                    report = day[1]
                    release = day[2]

                    if report is not None and release is not None:
                        duration = (
                            release - report
                        ).total_seconds() / 3600.0

                        duty_hours += duration

                # Apply requested delay
                duty_hours_with_delay = duty_hours + delay_h

                # -------------------------------------------------
                # Pairing flight hours
                # -------------------------------------------------
                pairing_flight_hours = sum(
                    float(row[8] or 0)
                    for row in flights
                )

                # -------------------------------------------------
                # Latest duty clock
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        duty_hours_7d,
                        flight_hours_28d,
                        last_rest_ended,
                        as_of_utc
                    FROM duty_clocks
                    WHERE crew_id = %s
                    ORDER BY as_of_utc DESC
                    LIMIT 1;
                """, (crew_id,))

                duty_clock = cur.fetchone()

                duty_7d_before = float(duty_clock[0] or 0) if duty_clock else 0.0
                flight_28d_before = float(duty_clock[1] or 0) if duty_clock else 0.0
                last_rest_ended = duty_clock[2] if duty_clock else None

                # -------------------------------------------------
                # Certification records
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        cert_type,
                        valid_from,
                        valid_to
                    FROM certifications
                    WHERE crew_id = %s;
                """, (crew_id,))

                certifications = cur.fetchall()

                # -------------------------------------------------
                # Rules from rules_vec
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        rule_id,
                        text,
                        params
                    FROM rules_vec
                    WHERE rule_id IN (
                        'RULE-FDP-01',
                        'RULE-DUTY-02',
                        'RULE-FLT-03',
                        'RULE-REST-04',
                        'RULE-QUAL-05',
                        'RULE-CERT-06',
                        'RULE-BASE-07'
                    );
                """)

                rule_rows = cur.fetchall()

        # =========================================================
        # Helper functions
        # =========================================================

        def get_rule_params(rule_id, default_limit=None):
            for row in rule_rows:
                if row[0] == rule_id:
                    params = row[2]

                    if isinstance(params, dict):
                        return params

                    return {}

            return {}

        def get_limit(rule_id, key, default):
            params = get_rule_params(rule_id)

            value = params.get(key)

            if value is None:
                return default

            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        # =========================================================
        # RULE-FDP-01
        # =========================================================

        fdp_limit = get_limit(
            "RULE-FDP-01",
            "limit",
            12.5
        )

        fdp_used = duty_hours_with_delay

        fdp_headroom = fdp_limit - fdp_used

        fdp_status = "PASS" if fdp_used <= fdp_limit else "FAIL"

        sector_count = len(flights)

        verdict_fdp = {
            "rule_id": "RULE-FDP-01",
            "status": fdp_status,
            "detail": (
                f"{fdp_used:.2f}h duty vs "
                f"{fdp_limit:.1f}h limit "
                f"({sector_count} sectors)"
            ),
            "used": round(fdp_used, 2),
            "limit": round(fdp_limit, 2),
            "headroom": round(fdp_headroom, 2),
            "date":legality_date.isoformat() if legality_date else None
        }

        # =========================================================
        # RULE-DUTY-02
        # =========================================================

        duty_limit = get_limit(
            "RULE-DUTY-02",
            "limit",
            60.0
        )

        duty_used = duty_7d_before + duty_hours_with_delay
        duty_headroom = duty_limit - duty_used

        duty_status = "PASS" if duty_used <= duty_limit else "FAIL"

        verdict_duty = {
            "rule_id": "RULE-DUTY-02",
            "status": duty_status,
            "detail": (
                f"{duty_used:.2f}h / "
                f"{duty_limit:.1f}h duty limit over 7 days"
            ),
            "used": round(duty_used, 2),
            "limit": round(duty_limit, 2),
            "headroom": round(duty_headroom, 2),
            "date": legality_date.isoformat() if legality_date else None
        }

        # =========================================================
        # RULE-FLT-03
        # =========================================================

        flight_limit = get_limit(
            "RULE-FLT-03",
            "limit",
            100.0
        )

        flight_used = flight_28d_before + pairing_flight_hours
        flight_headroom = flight_limit - flight_used

        flight_status = (
            "PASS"
            if flight_used <= flight_limit
            else "FAIL"
        )

        verdict_flight = {
            "rule_id": "RULE-FLT-03",
            "status": flight_status,
            "detail": (
                f"~{flight_used:.1f}h / "
                f"{flight_limit:.1f}h in the 28 days "
                f"to {legality_date}"
            ),
            "used": round(flight_used, 2),
            "limit": round(flight_limit, 2),
            "headroom": round(flight_headroom, 2),
            "date": legality_date.isoformat() if legality_date else None
        }

        # =========================================================
        # RULE-REST-04
        # =========================================================

        rest_limit = get_limit(
            "RULE-REST-04",
            "limit",
            12.0
        )

        rest_hours = None

        if last_rest_ended is not None and report_utc is not None:
            rest_hours = (
                report_utc - last_rest_ended
            ).total_seconds() / 3600.0

        if rest_hours is None:
            rest_status = "FAIL"
            rest_detail = "Unable to determine rest before report"

            verdict_rest = {
                "rule_id": "RULE-REST-04",
                "status": rest_status,
                "detail": rest_detail
            }
        else:
            rest_headroom = rest_hours - rest_limit
            rest_status = (
                "PASS"
                if rest_hours >= rest_limit
                else "FAIL"
            )

            verdict_rest = {
                "rule_id": "RULE-REST-04",
                "status": rest_status,
                "detail": (
                    f"{rest_hours:.1f}h rest before report "
                    f"(min {rest_limit:.1f}h)"
                ),
                "used": round(rest_hours, 2),
                "limit": round(rest_limit, 2),
                "headroom": round(rest_headroom, 2)
            }

        # =========================================================
        # RULE-QUAL-05
        # =========================================================

        aircraft_types = {
            row[9]
            for row in flights
            if row[9]
        }

        qualified = all(
            aircraft_type in crew_ratings
            for aircraft_type in aircraft_types
        )

        if qualified:
            qual_status = "PASS"

            if aircraft_types:
                aircraft_text = ", ".join(sorted(aircraft_types))
                qual_detail = f"{aircraft_text} rating valid"
            else:
                qual_detail = "Required aircraft rating valid"
        else:
            qual_status = "FAIL"
            missing_ratings = [
                aircraft_type
                for aircraft_type in aircraft_types
                if aircraft_type not in crew_ratings
            ]

            qual_detail = (
                "Missing rating for "
                + ", ".join(sorted(missing_ratings))
            )

        verdict_qual = {
            "rule_id": "RULE-QUAL-05",
            "status": qual_status,
            "detail": qual_detail
        }

        # =========================================================
        # RULE-CERT-06
        # =========================================================

        certification_status = "PASS"
        invalid_certifications = []

        for cert in certifications:
            cert_type = cert[0]
            valid_from = cert[1]
            valid_to = cert[2]

            for day in pairing_days:
                duty_date = day[0]

                if (
                    valid_from is not None
                    and duty_date < valid_from
                ) or (
                    valid_to is not None
                    and duty_date > valid_to
                ):
                    invalid_certifications.append(cert_type)
                    certification_status = "FAIL"
                    break

        if certification_status == "PASS":
            cert_detail = (
                "all certifications valid on every duty date"
            )
        else:
            cert_detail = (
                "invalid certifications: "
                + ", ".join(sorted(set(invalid_certifications)))
            )

        verdict_cert = {
            "rule_id": "RULE-CERT-06",
            "status": certification_status,
            "detail": cert_detail
        }

        # =========================================================
        # RULE-BASE-07
        # =========================================================

        report_station = (
            flights[0][4]
            if flights
            else None
        )

        if report_station == crew_base:
            base_status = "PASS"
            base_detail = f"{crew_base} own-base callout"
        else:
            base_status = "FAIL"
            base_detail = (
                f"report station {report_station} "
                f"does not match own base {crew_base}"
            )

        verdict_base = {
            "rule_id": "RULE-BASE-07",
            "status": base_status,
            "detail": base_detail
        }

        # =========================================================
        # Final result
        # =========================================================

        verdicts = [
            verdict_fdp,
            verdict_duty,
            verdict_flight,
            verdict_rest,
            verdict_qual,
            verdict_cert,
            verdict_base
        ]

        eligible = all(
            verdict["status"] == "PASS"
            for verdict in verdicts
        )

        return jsonify({
            "data": {
                "crew_id": crew_id,
                "pairing_id": pairing_id,
                 "date": legality_date.isoformat() if legality_date else None,
                "eligible": eligible,
                "verdicts": verdicts,
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to evaluate legality"
            }
        }), 500
    