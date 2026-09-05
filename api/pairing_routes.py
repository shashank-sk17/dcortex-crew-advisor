from flask import Blueprint, jsonify, request
from .db import get_db_connection

pairing_bp = Blueprint("pairing", __name__)

@pairing_bp.get("/api/v1/pairings/<pairing_id>")
def get_pairing(pairing_id):
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # 1. Pairing
                cur.execute("""
                    SELECT pairing_id, aircraft
                    FROM pairings
                    WHERE pairing_id = %s;
                """, (pairing_id,))

                pairing = cur.fetchone()

                if pairing is None:
                    return jsonify({
                        "error": {
                            "code": "PAIRING_NOT_FOUND",
                            "message": f"Pairing '{pairing_id}' not found"
                        }
                    }), 404

                # 2. Pairing days
                cur.execute("""
                    SELECT
                        date,
                        report_utc,
                        release_utc
                    FROM pairing_days
                    WHERE pairing_id = %s
                    ORDER BY date;
                """, (pairing_id,))

                day_rows = cur.fetchall()

                # 3. Flights in pairing
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
                        f.aircraft,
                        f.aircraft_type,
                        f.seats
                    FROM pairing_day_flights pdf
                    JOIN flights f
                      ON f.flight_id = pdf.flight_id
                    WHERE pdf.pairing_id = %s
                    ORDER BY pdf.date, pdf.leg_order;
                """, (pairing_id,))

                flight_rows = cur.fetchall()

                # 4. Crew assigned to pairing
                cur.execute("""
                    SELECT
                        pc.crew_id,
                        c.name,
                        c.rank,
                        pc.role,
                        c.base,
                        c.status
                    FROM pairing_crew pc
                    JOIN crew c
                      ON c.crew_id = pc.crew_id
                    WHERE pc.pairing_id = %s
                    ORDER BY pc.role, pc.crew_id;
                """, (pairing_id,))

                crew_rows = cur.fetchall()

        days = []

        for row in day_rows:
            days.append({
                "date": row[0].isoformat() if row[0] else None,
                "report_utc": row[1].isoformat() if row[1] else None,
                "release_utc": row[2].isoformat() if row[2] else None
            })

        flights = []

        for row in flight_rows:
            flights.append({
                "date": row[0].isoformat() if row[0] else None,
                "leg_order": row[1],
                "flight_id": row[2],
                "flight_no": row[3],
                "dep_station": row[4],
                "arr_station": row[5],
                "dep_utc": row[6].isoformat() if row[6] else None,
                "arr_utc": row[7].isoformat() if row[7] else None,
                "block_hours": float(row[8]) if row[8] is not None else None,
                "aircraft": row[9],
                "aircraft_type": row[10],
                "seats": row[11]
            })

        crew = []

        for row in crew_rows:
            crew.append({
                "crew_id": row[0],
                "name": row[1],
                "rank": row[2],
                "role": row[3],
                "base": row[4],
                "status": row[5]
            })

        return jsonify({
            "data": {
                "pairing_id": pairing[0],
                "aircraft": pairing[1],
                "days": days,
                "flights": flights,
                "crew": crew,
                "basis": [
                    "pairings.json",
                    "rosters.json",
                    "flights.json"
                ]
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve pairing"
            }
        }), 500

@pairing_bp.get("/api/v1/pairings/<pairing_id>/candidates")
def get_pairing_candidates(pairing_id):
    try:
        role = request.args.get("role")
        callout_utc = request.args.get("callout_utc")
        delay_h_raw = request.args.get("delay_h", "0")

        # ---------------------------------------------------------
        # Validate required parameters
        # ---------------------------------------------------------
        if not role:
            return jsonify({
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "'role' is required"
                }
            }), 400

        if not callout_utc:
            return jsonify({
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "'callout_utc' is required"
                }
            }), 400

        try:
            delay_h = float(delay_h_raw)
        except (TypeError, ValueError):
            return jsonify({
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "delay_h must be a number"
                }
            }), 400

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # -------------------------------------------------
                # Check pairing + get aircraft type
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        p.pairing_id,
                        p.aircraft,
                        f.aircraft_type
                    FROM pairings p
                    LEFT JOIN pairing_day_flights pdf
                        ON pdf.pairing_id = p.pairing_id
                    LEFT JOIN flights f
                        ON f.flight_id = pdf.flight_id
                    WHERE p.pairing_id = %s
                    ORDER BY pdf.date, pdf.leg_order
                    LIMIT 1;
                """, (pairing_id,))

                pairing = cur.fetchone()

                if pairing is None:
                    return jsonify({
                        "error": {
                            "code": "PAIRING_NOT_FOUND",
                            "message": "Pairing not found"
                        }
                    }), 404

                aircraft_type = pairing[2]

                # -------------------------------------------------
                # Get all crew
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
                    ORDER BY seniority ASC NULLS LAST, crew_id;
                """)

                all_crew = cur.fetchall()

                # -------------------------------------------------
                # Role filtering
                # -------------------------------------------------
                role_crew = [
                    r for r in all_crew
                    if r[2] == role
                ]

                # -------------------------------------------------
                # Aircraft qualification filtering
                #
                # Do this in Python so it works whether ratings
                # comes back as a PostgreSQL array or JSON-like list.
                # -------------------------------------------------
                qualified = []

                for r in role_crew:
                    ratings = r[4] or []

                    if isinstance(ratings, str):
                        ratings = [ratings]

                    if aircraft_type is None or aircraft_type in ratings:
                        qualified.append(r)

                # -------------------------------------------------
                # Available = active crew
                # -------------------------------------------------
                available = [
                    r for r in qualified
                    if r[7] == "active"
                ]

                # -------------------------------------------------
                # Current pairing crew
                # Don't recommend someone already assigned.
                # -------------------------------------------------
                cur.execute("""
                    SELECT crew_id
                    FROM pairing_crew
                    WHERE pairing_id = %s;
                """, (pairing_id,))

                assigned_ids = {
                    r[0] for r in cur.fetchall()
                }

                available = [
                    r for r in available
                    if r[0] not in assigned_ids
                ]

                # -------------------------------------------------
                # Build options
                # -------------------------------------------------
                options = []

                for r in available:
                    crew_id = r[0]
                    name = r[1]
                    base = r[3]
                    seniority = r[5]
                    reachability = r[6]

                    action = f"Assign {role} {crew_id}"

                    if r[7] == "reserve":
                        action += " (reserve callout)"

                    options.append({
                        "action": action,
                        "crew_id": crew_id,
                        "legal": True,
                        "rules_checked": [],
                        "cost_inr": None,
                        "delay_hours": delay_h,
                        "rank": len(options) + 1,
                        "cost_breakdown": {},
                        "coverage": "full pairing",
                        "reachability_minutes": reachability
                    })

                # -------------------------------------------------
                # Funnel counts
                # -------------------------------------------------
                all_count = len(all_crew)
                role_count = len(role_crew)
                qualified_count = len(qualified)
                available_count = len(available)

                funnel = [
                    {
                        "stage": "all_crew",
                        "count": all_count
                    },
                    {
                        "stage": "role",
                        "count": role_count,
                        "dropped": all_count - role_count,
                        "reason": f"not {role}"
                    },
                    {
                        "stage": "qualified",
                        "count": qualified_count,
                        "dropped": role_count - qualified_count,
                        "reason": "aircraft qualification"
                    },
                    {
                        "stage": "available",
                        "count": available_count,
                        "dropped": qualified_count - available_count,
                        "reason": "status or existing assignment"
                    },
                    {
                        "stage": "legal",
                        "count": available_count,
                        "dropped": 0,
                        "reason": None
                    }
                ]

                return jsonify({
                    "data": {
                        "pairing_id": pairing_id,
                        "role": role,
                        "callout_utc": callout_utc,
                        "funnel": funnel,
                        "options": options,
                        "near_misses": [],
                        "excluded": [],
                        "basis": [
                            "reserve_pool.json",
                            "crew.json",
                            "costs.json",
                            "rules.json"
                        ]
                    }
                }), 200

    except Exception as e:
        print("CANDIDATES ERROR:", repr(e))
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(e)
            }
        }), 500