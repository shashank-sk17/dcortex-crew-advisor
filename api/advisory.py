"""Business logic for POST /api/v1/advisory -- the main decision endpoint.
Combines crew, certifications, duty clocks, roster exceptions, pairings,
reserve pool, risk signals, rules and cost configuration, per the spec.

Scoped to scenario.type == "CREW_REPLACEMENT" for now (the type the spec's
own example uses); other types return a 400 via the route handler.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import queries


def run_advisory(payload: dict) -> dict:
    scenario = payload["scenario"]
    constraints = payload.get("constraints") or {}
    options = payload.get("options") or {"include_reserve": True, "max_candidates": 5}
    pairing_id = scenario.get("pairing_id")
    on_date = scenario["date"]

    affected_crew_id = (payload.get("affected_crew") or {}).get("crew_id")
    pool = queries.candidate_pool(
        rank=constraints.get("required_rank"), base=constraints.get("base")
    )
    pool = [c for c in pool if c["crew_id"] != affected_crew_id]
    reserve_ids = queries.reserve_crew_ids()  # one query, reused below instead of per-candidate is_reserve()
    if not options.get("include_reserve", True):
        pool = [c for c in pool if c["crew_id"] not in reserve_ids]

    costs_raw = queries.get_costs_raw()
    legality_by_crew = queries.compute_legality_bulk([c["crew_id"] for c in pool], pairing_id, on_date)
    candidates = []
    for crew in pool:
        legality = legality_by_crew[crew["crew_id"]]
        score = queries.score_candidate(crew, legality)
        cost_amount = _estimate_cost(crew, costs_raw, reserve_ids)
        candidates.append(
            {
                "crew_id": crew["crew_id"],
                "eligible": legality["eligible"],
                "score": score,
                "estimated_cost": {"currency": costs_raw["currency"], "amount": cost_amount},
                "reasons": legality["reasons"] if not legality["eligible"] else [
                    "Certification valid", "Duty limits available", "Within reachability window",
                ],
                "_crew": crew,  # dropped before serialization; kept for building `advisory` below
            }
        )

    # (legal, cost, then score as a tiebreak) -- matches the project's documented
    # ranking principle (legal, cost_inr, delay_hours); score alone would let a
    # senior-but-costlier candidate outrank a cheaper equally-legal one.
    candidates.sort(key=lambda c: (not c["eligible"], c["estimated_cost"]["amount"], -c["score"]))
    max_candidates = options.get("max_candidates", 5)
    top = candidates[:max_candidates]

    eligible_top = next((c for c in top if c["eligible"]), None)
    warnings: list[str] = []
    if eligible_top is None:
        advisory = {
            "status": "NO_LEGAL_OPTION",
            "recommended_action": "CANCEL",
            "recommended_crew": None,
            "reason": "No candidate satisfies all legality checks. Recommend cancellation "
                      "pending manual review of near-miss options.",
            "confidence": 0.4,
        }
        warnings.append("No eligible candidate found in the searched pool.")
    else:
        crew = eligible_top["_crew"]
        advisory = {
            "status": "ACTION_RECOMMENDED",
            "recommended_action": "REPLACE_CREW",
            "recommended_crew": {"crew_id": crew["crew_id"], "name": crew["name"], "rank": crew["rank"]},
            "reason": "Recommended candidate satisfies operational eligibility checks.",
            "confidence": eligible_top["score"],
        }

    # aggregate PASS/FAIL across the recommended (or best-attempted) candidate
    ref = eligible_top or (top[0] if top else None)
    if ref is not None:
        legality = legality_by_crew[ref["crew_id"]]  # already computed above, no need to re-query
        checks = {
            "certification": "PASS" if legality["checks"]["certification_valid"] else "FAIL",
            "duty_limits": "PASS" if legality["checks"]["duty_limits_ok"] else "FAIL",
            "rest": "PASS" if legality["checks"]["rest_ok"] else "FAIL",
            "roster_exceptions": "FAIL" if legality["checks"]["roster_exceptions"] else "PASS",
        }
    else:
        checks = {"certification": "FAIL", "duty_limits": "FAIL", "rest": "FAIL", "roster_exceptions": "FAIL"}
        warnings.append("No candidates matched the given constraints at all.")

    for c in top:
        c.pop("_crew", None)

    return {
        "request_id": payload["request_id"],
        "scenario": scenario,
        "advisory": advisory,
        "candidates": top,
        "checks": checks,
        "warnings": warnings,
        "meta": {"generated_at_utc": datetime.now(timezone.utc)},
    }


def _estimate_cost(crew: dict, costs_raw: dict, reserve_ids: set[str]) -> int:
    is_pilot = crew["rank"] in ("Captain", "First Officer")
    if crew["crew_id"] in reserve_ids:
        return costs_raw["reserve_callout_pilot"] if is_pilot else costs_raw["reserve_callout_cabin"]
    return costs_raw["dayoff_callout_pilot"] if is_pilot else costs_raw["dayoff_callout_cabin"]
