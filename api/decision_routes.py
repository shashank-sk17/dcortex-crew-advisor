from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

decision_bp = Blueprint("decision", __name__)

# In-memory storage for v1
decisions = []


@decision_bp.post("/api/v1/decisions")
def create_decision():
    try:
        body = request.get_json(silent=True)

        if not body:
            return jsonify({
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "Request body is required"
                }
            }), 400

        disruption_ref = body.get("disruption_ref")
        chosen_option = body.get("chosen_option")
        weights = body.get("weights")
        accepted = body.get("accepted")
        note = body.get("note")

        if not disruption_ref:
            return jsonify({
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "disruption_ref is required"
                }
            }), 400

        if not chosen_option:
            return jsonify({
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "chosen_option is required"
                }
            }), 400

        if accepted is None:
            return jsonify({
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "accepted is required"
                }
            }), 400

        if weights is not None and not isinstance(weights, dict):
            return jsonify({
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "weights must be an object"
                }
            }), 400

        if not isinstance(accepted, bool):
            return jsonify({
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "accepted must be true or false"
                }
            }), 400

        decision = {
            "id": len(decisions) + 1,
            "disruption_ref": disruption_ref,
            "chosen_option": chosen_option,
            "weights": weights or {},
            "accepted": accepted,
            "note": note,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        decisions.append(decision)

        return jsonify({
            "data": decision
        }), 201

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to create decision"
            }
        }), 500


@decision_bp.get("/api/v1/decisions")
def get_decisions():
    try:
        # Newest first
        result = list(reversed(decisions))

        return jsonify({
            "data": result,
            "meta": {
                "count": len(result)
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to fetch decisions"
            }
        }), 500