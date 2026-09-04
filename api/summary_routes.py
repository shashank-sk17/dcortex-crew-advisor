from flask import Blueprint, jsonify, request

from .db import get_db_connection


summary_bp = Blueprint("summary", __name__)


@summary_bp.get("/api/v1/summary")
def get_summary():
    date = request.args.get("date")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # Crew
                cur.execute("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'active') AS active,
                        COUNT(*) FILTER (
                            WHERE status IN ('training', 'leave')
                        ) AS inactive
                    FROM crew;
                """)
                crew = cur.fetchone()

                # Flights
                if date:
                    cur.execute("""
                        SELECT COUNT(*)
                        FROM flights
                        WHERE date = %s;
                    """, (date,))
                else:
                    cur.execute("""
                        SELECT COUNT(*)
                        FROM flights;
                    """)
                flights_total = cur.fetchone()[0]

                # Pairings
                if date:
                    cur.execute("""
                        SELECT COUNT(DISTINCT pairing_id)
                        FROM pairing_days
                        WHERE date = %s;
                    """, (date,))
                else:
                    cur.execute("""
                        SELECT COUNT(*)
                        FROM pairings;
                    """)
                pairings_total = cur.fetchone()[0]

                # Exceptions
                if date:
                    cur.execute("""
                        SELECT COUNT(*)
                        FROM roster_exceptions
                        WHERE date = %s;
                    """, (date,))
                else:
                    cur.execute("""
                        SELECT COUNT(*)
                        FROM roster_exceptions;
                    """)
                exceptions_total = cur.fetchone()[0]

                # Latest risk record for each crew member
                cur.execute("""
                    SELECT COUNT(*)
                    FROM (
                        SELECT DISTINCT ON (crew_id)
                            crew_id,
                            disruption_risk_score
                        FROM risk_signals
                        ORDER BY crew_id, as_of_utc DESC
                    ) latest_risk
                    WHERE disruption_risk_score >= 0.7;
                """)
                high_risk_crew = cur.fetchone()[0]

        return jsonify({
            "data": {
                "date": date,
                "crew": {
                    "total": crew[0],
                    "active": crew[1],
                    "inactive": crew[2]
                },
                "flights": {
                    "total": flights_total
                },
                "pairings": {
                    "total": pairings_total
                },
                "risk": {
                    "high_risk_crew": high_risk_crew
                },
                "exceptions": {
                    "open": exceptions_total
                }
            }
        }), 200

    except Exception as e:
        return jsonify({
            "error": {
                "code": "DATABASE_ERROR",
                "message": str(e)
            }
        }), 500