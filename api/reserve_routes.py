from datetime import datetime

from flask import Blueprint, jsonify, request

from .db import get_db_connection


reserve_bp = Blueprint("reserve", __name__)


@reserve_bp.get("/api/v1/reserves")
def get_reserves():
    try:
        date_param = request.args.get("date")
        base = request.args.get("base")
        role = request.args.get("role")
        covers_report_utc = request.args.get("covers_report_utc")

        # Validate covers_report_utc
        report_dt = None

        if covers_report_utc:
            try:
                report_dt = datetime.fromisoformat(
                    covers_report_utc.replace("Z", "+00:00")
                )
            except ValueError:
                return jsonify({
                    "error": {
                        "code": "INVALID_COVERS_REPORT_UTC",
                        "message": "covers_report_utc must be a valid ISO-8601 datetime"
                    }
                }), 400

        # Validate date
        if date_param:
            try:
                datetime.strptime(date_param, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({
                    "error": {
                        "code": "INVALID_DATE",
                        "message": "date must be in YYYY-MM-DD format"
                    }
                }), 400

        with get_db_connection() as conn:
            with conn.cursor() as cur:

                query = """
                    SELECT
                        rp.crew_id,
                        c.name,
                        c.rank,
                        rp.base,
                        rp.dates,
                        rp.oncall_start_utc,
                        rp.oncall_end_utc,
                        c.reachability_minutes
                    FROM reserve_pool rp
                    JOIN crew c
                        ON c.crew_id = rp.crew_id
                    WHERE 1 = 1
                """

                params = []

                if base:
                    query += " AND rp.base = %s"
                    params.append(base)

                if role:
                    query += " AND c.rank = %s"
                    params.append(role)

                query += """
                    ORDER BY
                        rp.base,
                        c.rank,
                        c.seniority ASC NULLS LAST,
                        rp.crew_id
                """

                cur.execute(query, params)
                rows = cur.fetchall()

        data = []

        for row in rows:
            (
                crew_id,
                name,
                crew_rank,
                crew_base,
                reserve_dates,
                oncall_start,
                oncall_end,
                reachability_minutes
            ) = row

            # Normalize reserve dates
            if reserve_dates is None:
                dates = []

            elif isinstance(reserve_dates, (list, tuple)):
                dates = [
                    d.isoformat() if hasattr(d, "isoformat") else str(d)
                    for d in reserve_dates
                ]

            else:
                dates = [str(reserve_dates)]

            # Filter by requested date
            if date_param and date_param not in dates:
                continue

            # Calculate whether reserve window covers report time
            covers = None

            if report_dt is not None:
                report_time = report_dt.time().replace(tzinfo=None)

                start_time = (
                    oncall_start.replace(tzinfo=None)
                    if hasattr(oncall_start, "replace")
                    else oncall_start
                )

                end_time = (
                    oncall_end.replace(tzinfo=None)
                    if hasattr(oncall_end, "replace")
                    else oncall_end
                )

                if start_time is not None and end_time is not None:

                    # Normal window, e.g. 03:00 -> 15:00
                    if start_time <= end_time:
                        covers = (
                            start_time
                            <= report_time
                            <= end_time
                        )

                    # Overnight window, e.g. 22:00 -> 06:00
                    else:
                        covers = (
                            report_time >= start_time
                            or report_time <= end_time
                        )

            data.append({
                "crew_id": crew_id,
                "name": name,
                "base": crew_base,
                "role": crew_rank,
                "window": {
                    "start": (
                        oncall_start.isoformat()
                        if oncall_start is not None
                        else None
                    ),
                    "end": (
                        oncall_end.isoformat()
                        if oncall_end is not None
                        else None
                    )
                },
                "covers": covers,
                "reachability_minutes": reachability_minutes
            })

        return jsonify({
            "data": data,
            "meta": {
                "count": len(data)
            }
        }), 200

    except Exception:
        return jsonify({
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Unable to retrieve reserve pool"
            }
        }), 500