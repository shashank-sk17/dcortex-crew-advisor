from flask import Blueprint, jsonify, request
from datetime import datetime
from .db import get_db_connection


summary_bp = Blueprint("summary", __name__)


@summary_bp.get("/api/v1/summary")
def get_summary():
    try:
        date_param = request.args.get("date")

        # date is required by the API contract
        if not date_param:
            return jsonify({
                "error": {
                    "code": "INVALID_DATE",
                    "message": "'date' is required"
                }
            }), 400

        try:
            summary_date = datetime.strptime(
                date_param, "%Y-%m-%d"
            ).date()
        except ValueError:
            return jsonify({
                "error": {
                    "code": "INVALID_DATE",
                    "message": "Invalid date format. Use YYYY-MM-DD"
                }
            }), 400

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # -------------------------------------------------
                # 1. CREW COUNTS
                # -------------------------------------------------

                cur.execute("""
                    SELECT COUNT(*)
                    FROM crew
                    WHERE status = 'active';
                """)
                total_active_crew = cur.fetchone()[0]

                # Crew assigned to a pairing on the requested date
                cur.execute("""
                    SELECT COUNT(DISTINCT pc.crew_id)
                    FROM pairing_crew pc
                    JOIN pairing_days pd
                        ON pd.pairing_id = pc.pairing_id
                    WHERE pd.date = %s;
                """, (summary_date,))
                on_duty = cur.fetchone()[0]

                off_duty = max(
                    total_active_crew - on_duty,
                    0
                )

                # Reserve pool for requested date
                cur.execute("""
                    SELECT COUNT(DISTINCT crew_id)
                    FROM reserve_pool
                    WHERE %s = ANY(dates);
                """, (summary_date,))
                reserve_count = cur.fetchone()[0]

                # Duty attention:
                # same deterministic threshold used by /crew:
                # duty headroom < 3h OR risk >= 0.7
                cur.execute("""
                    SELECT COUNT(*)
                    FROM (
                        SELECT
                            c.crew_id,
                            dc.duty_hours_7d,
                            rs.disruption_risk_score
                        FROM crew c

                        LEFT JOIN LATERAL (
                            SELECT duty_hours_7d
                            FROM duty_clocks
                            WHERE crew_id = c.crew_id
                            ORDER BY as_of_utc DESC
                            LIMIT 1
                        ) dc ON TRUE

                        LEFT JOIN LATERAL (
                            SELECT disruption_risk_score
                            FROM risk_signals
                            WHERE crew_id = c.crew_id
                            ORDER BY as_of_utc DESC
                            LIMIT 1
                        ) rs ON TRUE

                        WHERE c.status = 'active'
                    ) x
                    WHERE
                        (60 - COALESCE(duty_hours_7d, 0)) < 3
                        OR COALESCE(disruption_risk_score, 0) >= 0.7;
                """)
                needs_attention = cur.fetchone()[0]

                # -------------------------------------------------
                # 2. FLIGHT COUNTS
                # -------------------------------------------------

                cur.execute("""
                    SELECT COUNT(*)
                    FROM flights
                    WHERE date = %s;
                """, (summary_date,))
                total_flights = cur.fetchone()[0]

                # There is no persisted flight status/delay column
                # in the current DB schema, so these cannot be
                # truthfully derived yet.
                on_time = 0
                at_risk = 0
                delayed = 0
                cancelled = 0

                # -------------------------------------------------
                # 3. ALERTS
                # -------------------------------------------------

                # No alerts table exists in the current DB.
                # Do not fabricate alert records.
                critical_alerts = 0
                warning_alerts = 0

                # -------------------------------------------------
                # 4. RESERVE POOL BY BASE + ROLE
                # -------------------------------------------------

                cur.execute("""
                    SELECT
                        rp.base,
                        c.rank,
                        COUNT(DISTINCT rp.crew_id)
                    FROM reserve_pool rp
                    JOIN crew c
                        ON c.crew_id = rp.crew_id
                    WHERE %s = ANY(rp.dates)
                    GROUP BY rp.base, c.rank
                    ORDER BY rp.base, c.rank;
                """, (summary_date,))

                reserve_rows = cur.fetchall()

                by_base_role = {}

                for base, rank, count in reserve_rows:
                    by_base_role[f"{base}|{rank}"] = count

                # -------------------------------------------------
                # 5. AIRCRAFT
                # -------------------------------------------------

                cur.execute("""
                    SELECT COUNT(DISTINCT aircraft)
                    FROM flights
                    WHERE date = %s
                      AND aircraft IS NOT NULL;
                """, (summary_date,))
                aircraft_in_service = cur.fetchone()[0]

                # No AOG status is available in current DB.
                aircraft_aog = 0

                # -------------------------------------------------
                # 6. STATIONS
                # -------------------------------------------------

                # Current DB has no station-closure source.
                station_closures = []

        return jsonify({
            "data": {
                "date": summary_date.isoformat(),

                "crew": {
                    "on_duty": on_duty,
                    "off_duty": off_duty,
                    "reserve": reserve_count,
                    "needs_attention": needs_attention
                },

                "flights": {
                    "total": total_flights,
                    "on_time": on_time,
                    "at_risk": at_risk,
                    "delayed": delayed,
                    "cancelled": cancelled
                },

                "alerts": {
                    "critical": critical_alerts,
                    "warning": warning_alerts
                },

                "reserves": {
                    "by_base_role": by_base_role,
                    "depleted": []
                },

                "aircraft": {
                    "in_service": aircraft_in_service,
                    "aog": aircraft_aog
                },

                "stations": {
                    "closures": station_closures
                }
            }
        }), 200

    except Exception as e:
        print("SUMMARY ERROR:", repr(e))

        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to generate summary"
            }
        }), 500