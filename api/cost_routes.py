from flask import Blueprint, jsonify
from .db import get_db_connection

cost_bp = Blueprint("cost", __name__)


@cost_bp.get("/api/v1/costs")
def get_costs():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT *
            FROM costs
            LIMIT 1
        """)

        row = cur.fetchone()

        if not row:
            cur.close()
            conn.close()

            return jsonify({
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Cost configuration not found"
                }
            }), 404

        columns = [desc[0] for desc in cur.description]

        costs = dict(zip(columns, row))

        cur.close()
        conn.close()

        return jsonify({
            "data": costs
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve cost configuration"
            }
        }), 500