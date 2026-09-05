from flask import Blueprint, jsonify
from .db import get_db_connection

meta_bp = Blueprint("meta", __name__)


@meta_bp.get("/api/v1/meta")
def get_meta():
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:

                # -------------------------------------------------
                # 1. Snapshot timestamp
                # -------------------------------------------------
                cur.execute("""
                    SELECT MAX(as_of_utc)
                    FROM duty_clocks;
                """)
                snapshot_utc = cur.fetchone()[0]

                # -------------------------------------------------
                # 2. Dataset week
                # -------------------------------------------------
                cur.execute("""
                    SELECT
                        MIN(date),
                        MAX(date)
                    FROM flights;
                """)
                week_start, week_end = cur.fetchone()

                # -------------------------------------------------
                # 3. All dates in dataset
                # -------------------------------------------------
                cur.execute("""
                    SELECT DISTINCT date
                    FROM flights
                    WHERE date IS NOT NULL
                    ORDER BY date;
                """)
                dates = [
                    row[0].isoformat()
                    for row in cur.fetchall()
                ]

                # -------------------------------------------------
                # 4. Hub
                # -------------------------------------------------
                # Use the most common departure station
                cur.execute("""
                    SELECT dep_station
                    FROM flights
                    WHERE dep_station IS NOT NULL
                    GROUP BY dep_station
                    ORDER BY COUNT(*) DESC
                    LIMIT 1;
                """)
                hub_row = cur.fetchone()
                hub = hub_row[0] if hub_row else None

                # -------------------------------------------------
                # 5. Currency
                # -------------------------------------------------
                cur.execute("""
                    SELECT currency
                    FROM costs
                    LIMIT 1;
                """)
                currency_row = cur.fetchone()
                currency = currency_row[0] if currency_row else None

                # -------------------------------------------------
                # 6. Counts
                # -------------------------------------------------
                cur.execute("""
                    SELECT COUNT(*)
                    FROM crew;
                """)
                crew_count = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM flights;
                """)
                flight_count = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(*)
                    FROM pairings;
                """)
                pairing_count = cur.fetchone()[0]

                cur.execute("""
                    SELECT COUNT(DISTINCT crew_id)
                    FROM reserve_pool;
                """)
                reserve_count = cur.fetchone()[0]

        return jsonify({
            "data": {
                "snapshot_utc": (
                    snapshot_utc.isoformat()
                    if snapshot_utc else None
                ),

                "week": {
                    "start": (
                        week_start.isoformat()
                        if week_start else None
                    ),
                    "end": (
                        week_end.isoformat()
                        if week_end else None
                    )
                },

                "dates": dates,

                "hub": hub,

                "currency": currency,

                "counts": {
                    "crew": crew_count,
                    "flights": flight_count,
                    "pairings": pairing_count,
                    "reserves": reserve_count
                }
            }
        }), 200

    except Exception as e:
        print("META ERROR:", repr(e))

        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to fetch metadata"
            }
        }), 500