from datetime import datetime

from flask import Blueprint, jsonify, request

from .db import get_db_connection


alert_bp = Blueprint("alert", __name__)

# In-memory lifecycle state for v1
alert_states = {}


@alert_bp.get("/api/v1/alerts")
def get_alerts():
    try:
        date_str = request.args.get("date")
        severity_filter = request.args.get("severity")
        status_filter = request.args.get("status")

        if severity_filter and severity_filter not in {"critical", "warning"}:
            return jsonify({
                "error": {
                    "code": "INVALID_SEVERITY",
                    "message": "severity must be critical or warning"
                }
            }), 400

        if status_filter and status_filter not in {
            "open", "acknowledged", "resolved"
        }:
            return jsonify({
                "error": {
                    "code": "INVALID_STATUS",
                    "message": "status must be open, acknowledged, or resolved"
                }
            }), 400

        date_filter = None
        if date_str:
            try:
                date_filter = datetime.strptime(
                    date_str, "%Y-%m-%d"
                ).date()
            except ValueError:
                return jsonify({
                    "error": {
                        "code": "INVALID_DATE",
                        "message": "date must be in YYYY-MM-DD format"
                    }
                }), 400

        alerts = []

        conn = get_db_connection()
        cur = conn.cursor()

        # ---------------------------------------------------------
        # 1. Roster exceptions -> CRITICAL
        # ---------------------------------------------------------
        query = """
            SELECT crew_id, date, rule, note
            FROM roster_exceptions
        """

        cur.execute(query)

        for crew_id, alert_date, rule, note in cur.fetchall():

            if date_filter and alert_date != date_filter:
                continue

            alert_id = f"ROSTER-{crew_id}-{alert_date.isoformat()}"

            status = alert_states.get(alert_id, "open")

            alerts.append({
                "id": alert_id,
                "type": "roster_exception",
                "severity": "critical",
                "status": status,
                "crew_id": crew_id,
                "date": alert_date.isoformat(),
                "rule": rule,
                "message": note
            })

        # ---------------------------------------------------------
        # 2. Certification expiry -> WARNING
        # ---------------------------------------------------------
        cur.execute("""
            SELECT crew_id, cert_type, valid_to
            FROM certifications
        """)

        today = datetime.utcnow().date()

        for crew_id, cert_type, valid_to in cur.fetchall():

            if date_filter:
                days_to_expiry = (valid_to - date_filter).days
            else:
                days_to_expiry = (valid_to - today).days

            # Alert when certification expires within 3 days
            if 0 <= days_to_expiry <= 3:

                alert_id = f"CERT-{crew_id}-{cert_type}"

                status = alert_states.get(alert_id, "open")

                alerts.append({
                    "id": alert_id,
                    "type": "certification_expiry",
                    "severity": "warning",
                    "status": status,
                    "crew_id": crew_id,
                    "cert_type": cert_type,
                    "valid_to": valid_to.isoformat(),
                    "days_to_expiry": days_to_expiry
                })

        # ---------------------------------------------------------
        # 3. Duty clock -> WARNING
        # ---------------------------------------------------------
        cur.execute("""
            SELECT DISTINCT ON (crew_id)
                crew_id,
                as_of_utc,
                duty_hours_7d,
                flight_hours_28d
            FROM duty_clocks
            ORDER BY crew_id, as_of_utc DESC
        """)

        for crew_id, as_of_utc, duty_hours, flight_hours in cur.fetchall():

            # Duty limit = 60h / 7 days
            duty_headroom = 60 - duty_hours

            # Flight limit = 100h / 28 days
            flight_headroom = 100 - flight_hours

            if duty_headroom < 3 or flight_headroom < 3:

                alert_date = as_of_utc.date()
                alert_id = f"DUTY-{crew_id}-{alert_date}"

                status = alert_states.get(alert_id, "open")

                alerts.append({
                    "id": alert_id,
                    "type": "duty_clock",
                    "severity": "warning",
                    "status": status,
                    "crew_id": crew_id,
                    "as_of_utc": as_of_utc.isoformat(),
                    "duty_hours_7d": duty_hours,
                    "duty_headroom": duty_headroom,
                    "flight_hours_28d": flight_hours,
                    "flight_headroom": flight_headroom
                })

        # ---------------------------------------------------------
        # 4. Risk signals -> WARNING
        # ---------------------------------------------------------
        cur.execute("""
            SELECT DISTINCT ON (crew_id)
                crew_id,
                as_of_utc,
                disruption_risk_score,
                drivers
            FROM risk_signals
            ORDER BY crew_id, as_of_utc DESC
        """)

        for crew_id, as_of_utc, risk_score, drivers in cur.fetchall():

            if risk_score is not None and risk_score >= 0.70:

                alert_date = as_of_utc.date()
                alert_id = f"RISK-{crew_id}-{alert_date}"

                status = alert_states.get(alert_id, "open")

                alerts.append({
                    "id": alert_id,
                    "type": "risk_signal",
                    "severity": "warning",
                    "status": status,
                    "crew_id": crew_id,
                    "as_of_utc": as_of_utc.isoformat(),
                    "risk_score": float(risk_score),
                    "drivers": drivers
                })

        cur.close()
        conn.close()

        # ---------------------------------------------------------
        # Apply filters AFTER generating alerts
        # ---------------------------------------------------------
        if severity_filter:
            alerts = [
                a for a in alerts
                if a["severity"] == severity_filter
            ]

        if status_filter:
            alerts = [
                a for a in alerts
                if a["status"] == status_filter
            ]

        # Critical first, then warning
        severity_order = {
            "critical": 0,
            "warning": 1
        }

        alerts.sort(
            key=lambda x: (
                severity_order.get(x["severity"], 99),
                x.get("date", ""),
                x["id"]
            )
        )

        return jsonify({
            "data": alerts,
            "meta": {
                "count": len(alerts)
            }
        }), 200

    except Exception as e:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to fetch alerts"
            }
        }), 500
@alert_bp.post("/api/v1/alerts/<alert_id>/ack")
def acknowledge_alert(alert_id):
    try:
        alert_states[alert_id] = "acknowledged"

        return jsonify({
            "data": {
                "id": alert_id,
                "status": "acknowledged"
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to acknowledge alert"
            }
        }), 500


@alert_bp.post("/api/v1/alerts/<alert_id>/resolve")
def resolve_alert(alert_id):
    try:
        alert_states[alert_id] = "resolved"

        return jsonify({
            "data": {
                "id": alert_id,
                "status": "resolved"
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to resolve alert"
            }
        }), 500