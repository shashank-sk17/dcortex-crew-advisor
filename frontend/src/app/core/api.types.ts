/**
 * DTOs for every REST endpoint in docs/REST_API_v1.md.
 * MockApiService and HttpApiService both return exactly these shapes, so the
 * frontend is written once and the mock -> real swap is a config flag.
 */

export type IsoDate = string;   // 2026-09-15
export type IsoUtc = string;    // 2026-09-15T05:00:00Z
export type DelayRank = 'critical' | 'high' | 'medium' | 'low';
export type FlightStatus = 'scheduled' | 'at_risk' | 'delayed' | 'cancelled';
export type RuleStatus = 'PASS' | 'FAIL' | 'NOT_APPLICABLE';

/* ---------------------------------------------------------------- reference */

/**
 * Snapshot instant, week bounds and row counts — lets the app configure its
 * date picker. The live `GET /meta` (api/meta_routes.py) returns only
 * `{crew_count, flight_count, pairing_count, reserve_count}` today — none of
 * the fields below exist on the wire yet. Marked optional so the date-picker
 * degrades (falls back to the hardcoded default date) instead of throwing.
 */
export interface Meta {
  snapshot_utc?: IsoUtc;
  week?: { start: IsoDate; end: IsoDate };
  hub?: string;
  currency?: string;
  counts?: { crew: number; flights: number; pairings: number; reserves: number };
  dates?: IsoDate[];
}

/** One legality rule with its machine params and a plain-English gloss for popovers. */
export interface RuleDef {
  rule_id: string;
  text: string;
  params?: Record<string, unknown>;
  gloss: string;
}

/* ------------------------------------------------------------------ flights */

/** One row of the main flights board — schedule facts plus the computed disruption rank. */
export interface FlightRow {
  flight_id: string;
  flight_no: string;
  date: IsoDate;
  dep_station: string;
  arr_station: string;
  dep_utc: IsoUtc;
  arr_utc: IsoUtc;
  aircraft: string;
  aircraft_type: string;
  seats: number;
  pairing_id: string | null;
  status: FlightStatus;
  delay_rank: DelayRank;
  delay_rank_score: number;
  delay_rank_reasons: string[];
  slack_minutes: number | null;
  downstream_count: number;
  crew_fdp_headroom_min: number | null;
  basis: string[];
}

/** A crew member as named on a flight/pairing — id, name and the role they fill. */
export interface CrewLite {
  crew_id: string;
  name: string;
  role: string;
  rank: string;
}

/** Everything the flight drawer needs — the board row plus crew, timings and rule pressure. */
export interface FlightDetail extends FlightRow {
  crew: CrewLite[];
  report_utc: IsoUtc | null;
  release_utc: IsoUtc | null;
  block_hours: number;
  pax_estimate: number;
  prev_leg: string | null;
  next_leg: string | null;
  operating_crew_pressure: { crew_id: string; rule_id: string; headroom: number; status: RuleStatus }[];
}

/** A leg further down the same tail, with the delay it inherits — the cascade view. */
export interface DownstreamLeg {
  flight_id: string;
  flight_no: string;
  dep_utc: IsoUtc;
  arr_utc: IsoUtc;
  dep_station: string;
  arr_station: string;
  cumulative_delay_min: number;
  same_pairing: boolean;
}

/** One duty day of a pairing — its legs and the report/release bracket. */
export interface PairingDay {
  date: IsoDate;
  flights: string[];
  report_utc: IsoUtc;
  release_utc: IsoUtc;
}

/** A full pairing — the unit crew actually fly; drives day-2 orphan detection. */
export interface PairingDetail {
  pairing_id: string;
  aircraft: string;
  days: PairingDay[];
  crew: { crew_id: string; role: string }[];
  overnight_station: string | null;
}

/* ------------------------------------------------------------------- rules */

/** One rule's verdict with the arithmetic behind it — never a bare boolean. */
export interface RuleVerdict {
  rule_id: string;
  status: RuleStatus;
  detail: string;
  used?: number;
  limit?: number;
  headroom?: number;
  date?: IsoDate;
}

/* -------------------------------------------------------------- candidates */

/** One shrink step of the candidate search, with the count dropped and why. */
export interface FunnelStage {
  stage: string;
  count: number;
  dropped?: number;
  reason?: string;
}

/** A ranked resolution option — field names match the dataset answer keys verbatim. */
export interface Option {
  action: string;
  crew_id: string | null;
  legal: boolean;
  rules_checked: string[];
  cost_inr: number;
  delay_hours: number;
  rank: number;
  // additive — never replacing the above
  cost_breakdown?: Record<string, number>;
  blast_radius?: number;
  coverage?: string;
  reachability_minutes?: number;
  reasoning?: string;
  verdicts?: RuleVerdict[];
  unlock?: string | null;
  _score?: number;
}

/** A candidate that was ruled out, with the failing rule verdict(s). */
export interface ExcludedCandidate {
  crew_id: string;
  verdicts: RuleVerdict[];
}

/** The full "who can cover this" result — funnel, ranked options, near-misses, exclusions. */
export interface CandidateResult {
  pairing_id: string;
  role: string;
  callout_utc: IsoUtc;
  funnel: FunnelStage[];
  options: Option[];
  near_misses: Option[];
  excluded: ExcludedCandidate[];
  basis: string[];
}

/* -------------------------------------------------------------------- crew */

/** Why a crew member needs the controller's eyes, with the specific reasons. */
export interface Attention {
  flag: boolean;
  reasons: string[];
}

/** One row of the crew list — identity, current status and headline pressure. */
export interface CrewRow {
  crew_id: string;
  name: string;
  rank: string;
  base: string;
  ratings: string[];
  status: string;
  on_duty: boolean;
  current_assignment: { pairing_id: string | null; flight_id: string | null };
  next_report_utc: IsoUtc | null;
  duty_7d: number;
  duty_7d_headroom: number;
  disruption_risk_score: number;
  attention: Attention;
  basis: string[];
}

/** The calendar-day duty/flight window sums and rest state for a given date. */
/** Field names match the live `GET /crew/{id}/duty-clock` (api/crew_routes.py)
 * response verbatim — it uses `duty_hours_7d`/`flight_hours_28d`, not the
 * `duty_7d`/`flight_28d` this was previously typed with, and sends no `window`. */
export interface DutyClock {
  crew_id: string;
  date: IsoDate;
  as_of_utc?: IsoUtc;
  duty_hours_7d: number;
  duty_7d_headroom: number;
  flight_hours_28d: number;
  flight_28d_headroom: number;
  last_rest_ended: IsoUtc | null;
  rest_ok: boolean;
  window?: { start: IsoDate; end: IsoDate };
}

/** One certification with how many days of validity remain on the working date. */
export interface CertRow {
  type: string;
  valid_from: IsoDate;
  valid_to: IsoDate;
  days_to_expiry: number;
  expiring_soon: boolean;
}

/** A pairing this crew is rostered on this week — the crew-detail timeline. */
export interface CrewAssignment {
  pairing_id: string;
  date: IsoDate;
  flights: string[];
  report_utc: IsoUtc;
  release_utc: IsoUtc;
  role: string;
}

/**
 * Everything the crew drawer wants — the row plus duty clock, certs, risk and
 * assignments. `CrewRow`'s own fields and everything below are marked optional:
 * the live `GET /crew/{id}` (api/crew_routes.py) returns only
 * `{base, crew_id, name, rank, ratings, reachability_minutes, seniority,
 * status}` today — none of `attention`, `duty_clock`, `certifications`,
 * `risk`, `reserve_window`, `assignments`, or the rest of `CrewRow` exist on
 * the wire yet. Do not widen this back to required without confirming the
 * backend actually sends it — the drawer degrades to "not available" per
 * section rather than crashing, but a required type would silently lie again.
 */
export interface CrewDetail extends Partial<CrewRow> {
  crew_id: string;
  seniority: number;
  reachability_minutes: number;
  duty_clock?: DutyClock;
  certifications?: CertRow[];
  risk?: { score: number; drivers: string[] };
  reserve_window?: { start: string; end: string } | null;
  assignments?: CrewAssignment[];
}

/** A reserve crew member and whether their on-call window covers a required report time. */
export interface Reserve {
  crew_id: string;
  name: string;
  base: string;
  role: string;
  window: { start: string; end: string };
  covers: boolean | null;
  reachability_minutes: number;
}

/* ------------------------------------------------------------------ alerts */

export type AlertType =
  | 'DUTY_LIMIT_NEAR' | 'CERT_EXPIRING' | 'FLIGHT_AT_RISK' | 'RESERVE_POOL_LOW'
  | 'ROSTER_EXCEPTION' | 'DISRUPTION_REPORTED' | 'RESOLUTION_PROPOSED'
  // the live GET /alerts (api/alert_routes.py) sends these instead
  | 'certification_expiry' | 'risk_signal';
export type AlertSeverity = 'critical' | 'warning' | 'info';
export type AlertState = 'open' | 'ack' | 'resolved' | 'acknowledged';

/**
 * A human-in-the-loop item for the day — what's wrong, how bad, and the
 * fastest way to act. The live backend sends a much flatter, type-specific
 * shape than this — no `subject`/`title`/`detail`/`created_utc`/
 * `suggested_action`/`payload` at all, just `crew_id` plus fields particular
 * to `type` (`cert_type`/`valid_to`/`days_to_expiry` for
 * `certification_expiry`; `as_of_utc`/`drivers`/`risk_score` for
 * `risk_signal`). Everything below is optional so the UI can synthesize a
 * title/detail from whichever type-specific fields actually arrived —
 * see AlertsPanelComponent.describe() — rather than pretend they're absent.
 */
export interface Alert {
  id: string;
  type: AlertType;
  severity: AlertSeverity;
  status: AlertState;
  subject?: { kind: 'crew' | 'flight' | 'pairing' | 'station' | 'reserve_pool'; id: string };
  crew_id?: string;
  title?: string;
  detail?: string;
  created_utc?: IsoUtc;
  suggested_action?: { label: string; ask_prompt?: string; deep_link?: string } | null;
  payload?: Option[] | null;
  // certification_expiry
  cert_type?: string;
  valid_to?: IsoDate;
  days_to_expiry?: number;
  // risk_signal
  as_of_utc?: IsoUtc;
  drivers?: string[];
  risk_score?: number;
}

/* ---------------------------------------------------------------- sidebar */

/** The whole shift in one object — crew, flight, alert, reserve and station counts. */
export interface Summary {
  date: IsoDate;
  crew: { on_duty: number; off_duty: number; reserve: number; needs_attention: number };
  flights: {
    total: number; on_time: number; at_risk: number; delayed: number; cancelled: number;
    /** Sum of seats across today's critical/high delay_rank flights — the disruption's pax
     * footprint. Optional: the live `GET /summary` (api/summary_routes.py) doesn't send this
     * field at all yet — only the mock computes it. */
    pax_affected?: number;
    /** One row per critical/high delay_rank flight — the breakdown behind pax_affected.
     * Same live-backend gap as pax_affected above. */
    disrupted?: { flight_id: string; flight_no: string; route: string; pax: number }[];
  };
  alerts: { critical: number; warning: number };
  reserves: { by_base_role: Record<string, number>; depleted: string[] };
  aircraft: { in_service: number; aog: number };
  stations: { closures: { code: string; start_utc: IsoUtc; end_utc: IsoUtc; reason: string }[] };
}

/**
 * A pre-computed per-crew disruption-risk score with its drivers — a provided
 * input, not a model. The live `GET /risk-signals` (api/risk_signal_routes.py)
 * sends `risk_score`, not `disruption_risk_score`, and no `name` at all —
 * `name` is optional here; the sidebar falls back to `crew_id`.
 */
export interface RiskSignal {
  crew_id: string;
  name?: string;
  risk_score: number;
  drivers: string[];
}

/* --------------------------------------------------------------- decisions */

/** A logged controller accept/reject — the audit trail and future preference-pair data. */
export interface Decision {
  id: string;
  disruption_ref: string;
  chosen_option: Option | null;
  weights: Record<string, number>;
  accepted: boolean;
  note?: string;
  created_utc: IsoUtc;
}

/* ------------------------------------------------------------------ query */

/** Filters for the flights board — date is required, the rest narrow the list. */
export interface FlightQuery {
  date: IsoDate;
  station?: string;
  aircraft?: string;
  status?: FlightStatus;
  delay_rank?: DelayRank;
}

export type CrewFilter = 'needs_attention' | 'on_duty' | 'off_duty' | 'on_reserve' | 'all';

/** Filters for the crew list — filter/role/base/status/text, all optional. */
export interface CrewQuery {
  date?: IsoDate;
  filter?: CrewFilter;
  role?: string;
  base?: string;
  status?: string;
  q?: string;
}
