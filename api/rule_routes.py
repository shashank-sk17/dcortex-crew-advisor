from flask import Blueprint, jsonify, request
from .db import get_db_connection

rule_bp = Blueprint("rule", __name__)


@rule_bp.get("/api/v1/rules")
def get_rules():
    try:
        rule_id = request.args.get("rule_id")

        conn = get_db_connection()
        cur = conn.cursor()

        if rule_id:
            cur.execute("""
                SELECT rule_id, text, params
                FROM rules_vec
                WHERE rule_id = %s
            """, (rule_id,))
        else:
            cur.execute("""
                SELECT rule_id, text, params
                FROM rules_vec
                ORDER BY rule_id
            """)

        rows = cur.fetchall()

        cur.close()
        conn.close()

        rules = []

        for row in rows:
            rules.append({
                "rule_id": row[0],
                "text": row[1],
                "params": row[2] or {}
            })

        return jsonify({
            "data": rules,
            "meta": {
                "count": len(rules)
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve operational rules"
            }
        }), 500