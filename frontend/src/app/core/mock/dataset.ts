import { Injectable } from '@angular/core';

/* Raw dataset row shapes (only the fields the mock reads). */
export interface RawCrew {
  crew_id: string; name: string; rank: string; base: string;
  ratings: string[]; seniority: number; reachability_minutes: number; status: string;
}
export interface RawFlight {
  flight_id: string; flight_no: string; date: string;
  dep_station: string; arr_station: string; dep_utc: string; arr_utc: string;
  block_hours: number; aircraft: string; aircraft_type: string; seats: number;
}
export interface RawPairingDay { date: string; flights: string[]; report_utc: string; release_utc: string; }
export interface RawPairing {
  pairing_id: string; aircraft: string; days: RawPairingDay[];
  crew: { crew_id: string; role: string }[];
}
export interface RawRosters { pairings: RawPairing[]; flagged_exceptions: { crew_id: string; date: string; rule: string; note: string }[]; note: string; }
export interface RawDailyHistory { date: string; duty_hours: number; flight_hours: number; }
export interface RawDutyClock {
  crew_id: string; as_of_utc: string; duty_hours_7d: number; flight_hours_28d: number;
  last_rest_ended: string; daily_history: RawDailyHistory[];
}
export interface RawReserve {
  crew_id: string; base: string; dates: string[];
  oncall_window_utc: { start: string; end: string }; note: string;
}
export interface RawCert { crew_id: string; cert_type: string; valid_from: string; valid_to: string; }
export interface RawRule { rule_id: string; text: string; params?: Record<string, unknown>; }
export interface RawRules { time_convention: string; definitions: Record<string, string>; rules: RawRule[]; }
export interface RawCosts {
  currency: string; reserve_callout_pilot: number; reserve_callout_cabin: number;
  dayoff_callout_pilot: number; dayoff_callout_cabin: number; deadhead_positioning: number;
  delay_cost_per_duty_hour: number; cancellation_per_flight: number; hotel_overnight: number;
}
export interface RawRisk { crew_id: string; as_of_utc: string; disruption_risk_score: number; drivers: string[]; }
export interface RawScenario {
  scenario_id: string; difficulty: string; title: string;
  event: Record<string, unknown>; answer_key: Record<string, unknown>;
}

const BASE = 'assets/data';
const FILES = [
  'crew', 'flights', 'rosters', 'duty_clocks', 'reserve_pool',
  'certifications', 'rules', 'costs', 'risk_signals', 'scenarios',
] as const;

/**
 * Loads the vendored dataset (bundled into src/assets/data) once at app start.
 * MockApiService computes every endpoint response from this in memory —
 * the same relational data the real backend loads into `core/World`.
 */
@Injectable({ providedIn: 'root' })
export class Dataset {
  crew: RawCrew[] = [];
  flights: RawFlight[] = [];
  rosters: RawRosters = { pairings: [], flagged_exceptions: [], note: '' };
  dutyClocks: RawDutyClock[] = [];
  reserves: RawReserve[] = [];
  certs: RawCert[] = [];
  rules: RawRules = { time_convention: '', definitions: {}, rules: [] };
  costs!: RawCosts;
  risk: RawRisk[] = [];
  scenarios: RawScenario[] = [];

  // indexes
  crewById = new Map<string, RawCrew>();
  flightById = new Map<string, RawFlight>();
  pairingById = new Map<string, RawPairing>();
  dutyById = new Map<string, RawDutyClock>();
  reserveById = new Map<string, RawReserve>();
  certsByCrew = new Map<string, RawCert[]>();
  riskById = new Map<string, RawRisk>();
  /** crew_id -> pairings they are rostered on */
  pairingsByCrew = new Map<string, RawPairing[]>();

  readonly snapshotUtc = '2026-09-14T18:00:00Z';
  readonly weekStart = '2026-09-14';
  readonly weekEnd = '2026-09-20';

  private loaded = false;

  async load(): Promise<void> {
    if (this.loaded) return;
    const [crew, flights, rosters, duty, reserves, certs, rules, costs, risk, scenarios] =
      await Promise.all(FILES.map((f) => fetch(`${BASE}/${f}.json`).then((r) => r.json())));

    this.crew = crew;
    this.flights = flights;
    this.rosters = rosters;
    this.dutyClocks = duty;
    this.reserves = reserves;
    this.certs = certs;
    this.rules = rules;
    this.costs = costs;
    this.risk = risk;
    this.scenarios = scenarios;

    this.crew.forEach((c) => this.crewById.set(c.crew_id, c));
    this.flights.forEach((f) => this.flightById.set(f.flight_id, f));
    this.rosters.pairings.forEach((p) => this.pairingById.set(p.pairing_id, p));
    this.dutyClocks.forEach((d) => this.dutyById.set(d.crew_id, d));
    this.reserves.forEach((r) => this.reserveById.set(r.crew_id, r));
    this.risk.forEach((r) => this.riskById.set(r.crew_id, r));
    this.certs.forEach((c) => {
      const arr = this.certsByCrew.get(c.crew_id) ?? [];
      arr.push(c);
      this.certsByCrew.set(c.crew_id, arr);
    });
    this.rosters.pairings.forEach((p) =>
      p.crew.forEach((m) => {
        const arr = this.pairingsByCrew.get(m.crew_id) ?? [];
        arr.push(p);
        this.pairingsByCrew.set(m.crew_id, arr);
      }),
    );

    this.loaded = true;
  }

  dates(): string[] {
    const out: string[] = [];
    const d = new Date(this.weekStart + 'T00:00:00Z');
    const end = new Date(this.weekEnd + 'T00:00:00Z');
    while (d <= end) {
      out.push(d.toISOString().slice(0, 10));
      d.setUTCDate(d.getUTCDate() + 1);
    }
    return out;
  }
}
