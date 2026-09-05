from flask import Blueprint, jsonify
from .db import get_db_connection

meta_bp = Blueprint("meta", __name__)


@meta_bp.get("/api/v1/meta")
def get_meta():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM crew) AS crew_count,
                (SELECT COUNT(*) FROM flights) AS flight_count,
                (SELECT COUNT(*) FROM pairings) AS pairing_count,
                (SELECT COUNT(*) FROM reserve_pool) AS reserve_count
        """)

        crew_count, flight_count, pairing_count, reserve_count = cur.fetchone()

        cur.close()
        conn.close()

        return jsonify({
            "data": {
                "crew_count": crew_count,
                "flight_count": flight_count,
                "pairing_count": pairing_count,
                "reserve_count": reserve_count
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to fetch metadata"
            }
        }), 500