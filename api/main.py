from __future__ import annotations

from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from . import advisory, queries, schemas

app = FastAPI(title="Crew Operations Advisor API", version="v1")


def _not_found(code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content=schemas.ErrorResponse(error=schemas.ErrorBody(code=code, message=message)).model_dump(mode="json"),
    )


# ---------------------------------------------------------------- 1/2. crew

@app.get("/api/v1/crew", response_model=schemas.CrewListResponse)
def crew_list(base: str | None = None, status: str | None = None, rank: str | None = None):
    rows = queries.list_crew(base, status, rank)
    return schemas.CrewListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


@app.get("/api/v1/crew/{crew_id}", response_model=schemas.CrewDetailResponse)
def crew_detail(crew_id: str):
    row = queries.get_crew(crew_id)
    if not row:
        return _not_found("CREW_NOT_FOUND", "Crew member not found")
    return schemas.CrewDetailResponse(data=row)


# ---------------------------------------------------------------- 3. duty clock

@app.get("/api/v1/crew/{crew_id}/duty-clock", response_model=schemas.DutyClockResponse)
def duty_clock(crew_id: str):
    row = queries.get_duty_clock(crew_id)
    if not row:
        return _not_found("DUTY_CLOCK_NOT_FOUND", "Duty clock not found")
    return schemas.DutyClockResponse(data=row)


# ---------------------------------------------------------------- 4. certifications

@app.get("/api/v1/crew/{crew_id}/certifications", response_model=schemas.CertificationListResponse)
def certifications(crew_id: str):
    if not queries.get_crew(crew_id):
        return _not_found("CREW_NOT_FOUND", "Crew member not found")
    rows = queries.list_certifications(crew_id)
    return schemas.CertificationListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


# ---------------------------------------------------------------- 5. roster exceptions

@app.get("/api/v1/crew/{crew_id}/exceptions", response_model=schemas.RosterExceptionListResponse)
def exceptions(crew_id: str, from_: date | None = Query(None, alias="from"), to: date | None = None):
    if not queries.get_crew(crew_id):
        return _not_found("CREW_NOT_FOUND", "Crew member not found")
    rows = queries.list_roster_exceptions(crew_id, from_, to)
    return schemas.RosterExceptionListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


# ---------------------------------------------------------------- 6. crew risk

@app.get("/api/v1/crew/{crew_id}/risk", response_model=schemas.RiskSignalResponse)
def crew_risk(crew_id: str):
    row = queries.get_risk_signal(crew_id)
    if not row:
        return _not_found("RISK_NOT_FOUND", "No risk signal found")
    return schemas.RiskSignalResponse(data=row)


# ---------------------------------------------------------------- 7/8. flights

@app.get("/api/v1/flights", response_model=schemas.FlightListResponse)
def flights_list(
    date: date | None = None, dep_station: str | None = None,
    arr_station: str | None = None, aircraft_type: str | None = None,
):
    rows = queries.list_flights(date, dep_station, arr_station, aircraft_type)
    return schemas.FlightListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


@app.get("/api/v1/flights/{flight_id}", response_model=schemas.FlightDetailResponse)
def flight_detail(flight_id: str):
    row = queries.get_flight(flight_id)
    if not row:
        return _not_found("FLIGHT_NOT_FOUND", "Flight not found")
    return schemas.FlightDetailResponse(data=row)


# ---------------------------------------------------------------- 9/10. pairings

@app.get("/api/v1/pairings", response_model=schemas.PairingListResponse)
def pairings_list(date: date | None = None, aircraft: str | None = None):
    rows = queries.list_pairings(date, aircraft)
    return schemas.PairingListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


@app.get("/api/v1/pairings/{pairing_id}", response_model=schemas.PairingDetailResponse)
def pairing_detail(pairing_id: str):
    row = queries.get_pairing(pairing_id)
    if not row:
        return _not_found("PAIRING_NOT_FOUND", "Pairing not found")
    return schemas.PairingDetailResponse(data=row)


# ---------------------------------------------------------------- 11. reserves

@app.get("/api/v1/reserves", response_model=schemas.ReserveListResponse)
def reserves_list(base: str | None = None, date: date | None = None):
    rows = queries.list_reserves(base, date)
    return schemas.ReserveListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


# ---------------------------------------------------------------- 12. risk signals

@app.get("/api/v1/risk-signals", response_model=schemas.RiskSignalListResponse)
def risk_signals_list(crew_id: str | None = None, as_of_utc: str | None = None):
    rows = queries.list_risk_signals(crew_id)
    return schemas.RiskSignalListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


# ---------------------------------------------------------------- 13. costs

@app.get("/api/v1/costs", response_model=schemas.CostsResponse)
def costs():
    return schemas.CostsResponse(data=queries.get_costs())


# ---------------------------------------------------------------- 14. rules

@app.get("/api/v1/rules", response_model=schemas.RuleListResponse)
def rules_list(rule_id: str | None = None):
    rows = queries.list_rules(rule_id)
    return schemas.RuleListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


# ---------------------------------------------------------------- 15. legality

@app.get("/api/v1/crew/{crew_id}/legality", response_model=schemas.LegalityResponse)
def legality(crew_id: str, pairing_id: str, date: date | None = None):
    if not pairing_id:
        return JSONResponse(
            status_code=400,
            content=schemas.ErrorResponse(
                error=schemas.ErrorBody(code="MISSING_PARAMETER", message="pairing_id is required")
            ).model_dump(mode="json"),
        )
    if not queries.get_pairing(pairing_id):
        return _not_found("PAIRING_NOT_FOUND", "Pairing not found")
    on_date = date or __import__("datetime").date.today()
    return schemas.LegalityResponse(data=queries.compute_legality(crew_id, pairing_id, on_date))


# ---------------------------------------------------------------- 16. candidates

@app.get("/api/v1/pairings/{pairing_id}/candidates", response_model=schemas.CandidateListResponse)
def candidates(pairing_id: str, date: date | None = None, rank: str | None = None):
    pairing = queries.get_pairing(pairing_id)
    if not pairing:
        return _not_found("PAIRING_NOT_FOUND", "Pairing not found")
    on_date = date or pairing["days"][0]["date"]
    pool = queries.candidate_pool(rank=rank, base=None)
    legality_by_crew = queries.compute_legality_bulk([c["crew_id"] for c in pool], pairing_id, on_date)
    rows = []
    for crew in pool:
        legality_result = legality_by_crew[crew["crew_id"]]
        score = queries.score_candidate(crew, legality_result)
        rows.append(
            {
                "crew_id": crew["crew_id"], "name": crew["name"], "rank": crew["rank"],
                "eligible": legality_result["eligible"], "score": score,
                "reasons": legality_result["reasons"] if not legality_result["eligible"] else [
                    "Certification valid", "Duty limits available", "Within reachability window",
                ],
            }
        )
    rows.sort(key=lambda r: (-r["eligible"], -r["score"]))
    return schemas.CandidateListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


# ---------------------------------------------------------------- 17. controller notes

@app.get("/api/v1/crew/{crew_id}/notes", response_model=schemas.ControllerNoteListResponse)
def notes(crew_id: str, date: date | None = None, rule: str | None = None):
    rows = queries.list_controller_notes(crew_id, date, rule)
    return schemas.ControllerNoteListResponse(data=rows, meta=schemas.Meta(count=len(rows)))


# ---------------------------------------------------------------- 18. summary

@app.get("/api/v1/summary", response_model=schemas.SummaryResponse)
def summary(date: date | None = None):
    on_date = date or __import__("datetime").date.today()
    return schemas.SummaryResponse(data=queries.get_summary(on_date))


# ---------------------------------------------------------------- 19. advisory

@app.post("/api/v1/advisory", response_model=schemas.AdvisoryResponse)
def create_advisory(request: schemas.AdvisoryRequest):
    if request.scenario.type != "CREW_REPLACEMENT":
        return JSONResponse(
            status_code=400,
            content=schemas.ErrorResponse(
                error=schemas.ErrorBody(code="INVALID_REQUEST", message="Unsupported scenario.type",
                                        details=[schemas.ErrorDetail(field="scenario.type", issue="only CREW_REPLACEMENT is implemented")])
            ).model_dump(mode="json"),
        )
    pairing_id = request.scenario.pairing_id
    if not pairing_id:
        return JSONResponse(
            status_code=400,
            content=schemas.ErrorResponse(
                error=schemas.ErrorBody(code="INVALID_REQUEST", message="Invalid advisory request",
                                        details=[schemas.ErrorDetail(field="scenario.pairing_id", issue="This field is required")])
            ).model_dump(mode="json"),
        )
    if not queries.get_pairing(pairing_id):
        return _not_found("RESOURCE_NOT_FOUND", "Referenced pairing or flight was not found")

    try:
        result = advisory.run_advisory(request.model_dump())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content=schemas.ErrorResponse(
                error=schemas.ErrorBody(code="ADVISORY_FAILED", message="Unable to generate advisory")
            ).model_dump(mode="json"),
        )
    return schemas.AdvisoryResponse(data=result)
