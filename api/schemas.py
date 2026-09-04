from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from .pii import PIISafeModel

# ---------------------------------------------------------------- shared

class ErrorDetail(PIISafeModel):
    field: str
    issue: str


class ErrorBody(PIISafeModel):
    code: str
    message: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(PIISafeModel):
    error: ErrorBody


class Meta(PIISafeModel):
    count: int


# ---------------------------------------------------------------- 1/2. Crew

class Crew(PIISafeModel):
    crew_id: str
    name: str
    rank: str
    base: str
    ratings: list[str]
    seniority: int
    reachability_minutes: int
    status: str


class CrewListResponse(PIISafeModel):
    data: list[Crew]
    meta: Meta


class CrewDetailResponse(PIISafeModel):
    data: Crew


# ---------------------------------------------------------------- 3. Duty clock

class DutyClock(PIISafeModel):
    crew_id: str
    as_of_utc: datetime
    duty_hours_7d: float
    flight_hours_28d: float
    last_rest_ended: datetime


class DutyClockResponse(PIISafeModel):
    data: DutyClock


# ---------------------------------------------------------------- 4. Certifications

class Certification(PIISafeModel):
    crew_id: str
    cert_type: str
    valid_from: date
    valid_to: date


class CertificationListResponse(PIISafeModel):
    data: list[Certification]
    meta: Meta


# ---------------------------------------------------------------- 5. Roster exceptions

class RosterException(PIISafeModel):
    crew_id: str
    date: date
    rule: str
    note: str


class RosterExceptionListResponse(PIISafeModel):
    data: list[RosterException]
    meta: Meta


# ---------------------------------------------------------------- 6/12. Risk signals

class RiskSignal(PIISafeModel):
    crew_id: str
    as_of_utc: datetime
    disruption_risk_score: float
    drivers: list[str]


class RiskSignalResponse(PIISafeModel):
    data: RiskSignal


class RiskSignalListResponse(PIISafeModel):
    data: list[RiskSignal]
    meta: Meta


# ---------------------------------------------------------------- 7/8. Flights

class Flight(PIISafeModel):
    flight_id: str
    flight_no: str
    date: date
    dep_station: str
    arr_station: str
    dep_utc: datetime
    arr_utc: datetime
    block_hours: float
    aircraft: str
    aircraft_type: str
    seats: int


class FlightListResponse(PIISafeModel):
    data: list[Flight]
    meta: Meta


class FlightDetailResponse(PIISafeModel):
    data: Flight


# ---------------------------------------------------------------- 9/10. Pairings

class PairingSummary(PIISafeModel):
    pairing_id: str
    aircraft: str


class PairingListResponse(PIISafeModel):
    data: list[PairingSummary]
    meta: Meta


class PairingDayFlight(PIISafeModel):
    flight_id: str
    leg_order: int


class PairingDay(PIISafeModel):
    date: date
    report_utc: datetime
    release_utc: datetime
    flights: list[PairingDayFlight]


class PairingDetail(PIISafeModel):
    pairing_id: str
    aircraft: str
    days: list[PairingDay]


class PairingDetailResponse(PIISafeModel):
    data: PairingDetail


# ---------------------------------------------------------------- 11. Reserve pool

class Reserve(PIISafeModel):
    crew_id: str
    base: str
    dates: list[date]
    oncall_start_utc: datetime
    oncall_end_utc: datetime


class ReserveListResponse(PIISafeModel):
    data: list[Reserve]
    meta: Meta


# ---------------------------------------------------------------- 13. Costs

class Costs(PIISafeModel):
    currency: str
    reserve_dayoff_callout: int
    deadhead: int
    delay: int
    cancellation: int
    hotel: int


class CostsResponse(PIISafeModel):
    data: Costs


# ---------------------------------------------------------------- 14. Rules

class Rule(PIISafeModel):
    rule_id: str
    text: str
    params: dict


class RuleListResponse(PIISafeModel):
    data: list[Rule]
    meta: Meta


# ---------------------------------------------------------------- 15. Legality

class LegalityChecks(PIISafeModel):
    certification_valid: bool
    duty_limits_ok: bool
    rest_ok: bool
    roster_exceptions: bool
    qualification_valid: bool  # additive -- not in the PDF sample, but required for a correct `eligible` verdict


class Legality(PIISafeModel):
    crew_id: str
    pairing_id: str
    date: date
    eligible: bool
    reasons: list[str]
    checks: LegalityChecks


class LegalityResponse(PIISafeModel):
    data: Legality


# ---------------------------------------------------------------- 16. Candidates

class Candidate(PIISafeModel):
    crew_id: str
    name: str
    rank: str
    eligible: bool
    score: float
    reasons: list[str]


class CandidateListResponse(PIISafeModel):
    data: list[Candidate]
    meta: Meta


# ---------------------------------------------------------------- 17. Controller notes

class ControllerNote(PIISafeModel):
    id: int
    crew_id: str
    date: date
    rule: str
    note: str


class ControllerNoteListResponse(PIISafeModel):
    data: list[ControllerNote]
    meta: Meta


# ---------------------------------------------------------------- 18. Summary

class SummaryCrew(PIISafeModel):
    total: int
    active: int
    on_leave: int


class SummaryFlights(PIISafeModel):
    total: int


class SummaryPairings(PIISafeModel):
    total: int


class SummaryRisk(PIISafeModel):
    high_risk_crew: int


class SummaryExceptions(PIISafeModel):
    open: int


class Summary(PIISafeModel):
    date: date
    crew: SummaryCrew
    flights: SummaryFlights
    pairings: SummaryPairings
    risk: SummaryRisk
    exceptions: SummaryExceptions


class SummaryResponse(PIISafeModel):
    data: Summary


# ---------------------------------------------------------------- 19. Advisory

class AdvisoryScenario(PIISafeModel):
    type: str
    date: date
    pairing_id: str | None = None
    flight_id: str | None = None


class AdvisoryAffectedCrew(PIISafeModel):
    crew_id: str


class AdvisoryConstraints(PIISafeModel):
    required_rank: str | None = None
    aircraft_type: str | None = None
    base: str | None = None


class AdvisoryOptions(PIISafeModel):
    include_reserve: bool = True
    max_candidates: int = Field(default=5, ge=1, le=50)


class AdvisoryRequest(PIISafeModel):
    request_id: str
    scenario: AdvisoryScenario
    affected_crew: AdvisoryAffectedCrew | None = None
    constraints: AdvisoryConstraints | None = None
    options: AdvisoryOptions = AdvisoryOptions()


class EstimatedCost(PIISafeModel):
    currency: str
    amount: int


class AdvisoryCandidate(PIISafeModel):
    crew_id: str
    eligible: bool
    score: float
    estimated_cost: EstimatedCost
    reasons: list[str]


class AdvisoryChecks(PIISafeModel):
    certification: str
    duty_limits: str
    rest: str
    roster_exceptions: str


class RecommendedCrew(PIISafeModel):
    crew_id: str
    name: str
    rank: str


class AdvisoryVerdict(PIISafeModel):
    status: str
    recommended_action: str | None
    recommended_crew: RecommendedCrew | None
    reason: str
    confidence: float


class AdvisoryResponseMeta(PIISafeModel):
    generated_at_utc: datetime


class AdvisoryResponseData(PIISafeModel):
    request_id: str
    scenario: AdvisoryScenario
    advisory: AdvisoryVerdict
    candidates: list[AdvisoryCandidate]
    checks: AdvisoryChecks
    warnings: list[str]
    meta: AdvisoryResponseMeta


class AdvisoryResponse(PIISafeModel):
    data: AdvisoryResponseData
