from flask import Blueprint, jsonify, request
from .db import get_db_connection

risk_signal_bp = Blueprint("risk_signal", __name__)


@risk_signal_bp.get("/api/v1/risk-signals")
def get_risk_signals():
    try:
        threshold_str = request.args.get("threshold", "0.5")

        # Validate threshold
        try:
            threshold = float(threshold_str)
        except (TypeError, ValueError):
            return jsonify({
                "error": {
                    "code": "INVALID_THRESHOLD",
                    "message": "threshold must be a number between 0 and 1"
                }
            }), 400

        if not 0 <= threshold <= 1:
            return jsonify({
                "error": {
                    "code": "INVALID_THRESHOLD",
                    "message": "threshold must be a number between 0 and 1"
                }
            }), 400

        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                crew_id,
                as_of_utc,
                disruption_risk_score,
                drivers
            FROM risk_signals
            WHERE disruption_risk_score >= %s
            ORDER BY disruption_risk_score DESC
        """, (threshold,))

        rows = cur.fetchall()

        cur.close()
        conn.close()

        signals = []

        for crew_id, as_of_utc, risk_score, drivers in rows:
            signals.append({
                "crew_id": crew_id,
                "as_of_utc": as_of_utc.isoformat()
                    if as_of_utc else None,
                "risk_score": float(risk_score)
                    if risk_score is not None else None,
                "drivers": drivers
            })

        return jsonify({
            "data": signals,
            "meta": {
                "count": len(signals),
                "threshold": threshold
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to fetch risk signals"
            }
        }), 500