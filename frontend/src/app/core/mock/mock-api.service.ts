import { Injectable, inject } from '@angular/core';
import { Observable, delay, of } from 'rxjs';
import { Dataset } from './dataset';
import * as D from './derive';
import {
  Alert, CandidateResult, CrewDetail, CrewQuery, CrewRow, Decision, DownstreamLeg,
  DutyClock, FlightDetail, FlightQuery, FlightRow, Meta, PairingDetail, Reserve, RiskSignal,
  RuleDef, RuleVerdict, Summary,
} from '../api.types';
import { ApiPort } from '../api.port';

const LAT = 70; // simulated latency ms

/** Every endpoint in docs/REST_API_v1.md, computed from the bundled dataset. */
@Injectable({ providedIn: 'root' })
export class MockApiService implements ApiPort {
  private ds = inject(Dataset);
  private alertState = new Map<string, 'open' | 'ack' | 'resolved'>();
  private decisions: Decision[] = [];

  private ok<T>(v: T): Observable<T> {
    return of(v).pipe(delay(LAT));
  }

  /* -------- reference -------- */
  meta(): Observable<Meta> {
    return this.ok({
      snapshot_utc: this.ds.snapshotUtc,
      week: { start: this.ds.weekStart, end: this.ds.weekEnd },
      hub: 'BLR', currency: 'INR',
      counts: {
        crew: this.ds.crew.length, flights: this.ds.flights.length,
        pairings: this.ds.rosters.pairings.length, reserves: this.ds.reserves.length,
      },
      dates: this.ds.dates(),
    });
  }

  rules(): Observable<RuleDef[]> {
    return this.ok(this.ds.rules.rules.map((r) => ({
      rule_id: r.rule_id, text: r.text, params: r.params,
      gloss: GLOSS[r.rule_id] ?? r.text,
    })));
  }

  costs(): Observable<Record<string, unknown>> {
    return this.ok(this.ds.costs as unknown as Record<string, unknown>);
  }

  /* -------- flights -------- */
  flights(q: FlightQuery): Observable<FlightRow[]> {
    let rows = this.ds.flights
      .filter((f) => f.date === q.date)
      .map((f) => D.toFlightRow(this.ds, f));
    if (q.station) rows = rows.filter((r) => r.dep_station === q.station || r.arr_station === q.station);
    if (q.aircraft) rows = rows.filter((r) => r.aircraft === q.aircraft);
    if (q.status) rows = rows.filter((r) => r.status === q.status);
    if (q.delay_rank) rows = rows.filter((r) => r.delay_rank === q.delay_rank);
    rows.sort((a, b) => b.delay_rank_score - a.delay_rank_score || a.dep_utc.localeCompare(b.dep_utc));
    return this.ok(rows);
  }

  flight(flightId: string): Observable<FlightDetail> {
    const f = this.ds.flightById.get(flightId);
    if (!f) return this.ok(null as unknown as FlightDetail);
    const row = D.toFlightRow(this.ds, f);
    const p = D.pairingForFlight(this.ds, flightId);
    const day = p?.days.find((d) => d.flights.includes(flightId)) ?? null;
    const legs = this.ds.flights
      .filter((x) => x.aircraft === f.aircraft && x.date === f.date)
      .sort((a, b) => a.dep_utc.localeCompare(b.dep_utc));
    const i = legs.findIndex((x) => x.flight_id === flightId);
    return this.ok({
      ...row,
      crew: (p?.crew ?? []).map((m) => {
        const c = this.ds.crewById.get(m.crew_id)!;
        return { crew_id: m.crew_id, name: c?.name ?? m.crew_id, role: m.role, rank: c?.rank ?? m.role };
      }),
      report_utc: day?.report_utc ?? null,
      release_utc: day?.release_utc ?? null,
      block_hours: f.block_hours,
      pax_estimate: f.seats,
      prev_leg: i > 0 ? legs[i - 1].flight_id : null,
      next_leg: i >= 0 && i < legs.length - 1 ? legs[i + 1].flight_id : null,
      operating_crew_pressure: (p?.crew ?? []).slice(0, 2).map((m) => {
        const head = 60 - D.duty7d(this.ds, m.crew_id);
        return { crew_id: m.crew_id, rule_id: 'RULE-DUTY-02', headroom: Math.round(head * 100) / 100, status: head < 0 ? 'FAIL' as const : 'PASS' as const };
      }),
    });
  }

  downstream(flightId: string, delayMin = 90): Observable<DownstreamLeg[]> {
    const f = this.ds.flightById.get(flightId);
    if (!f) return this.ok([]);
    const p = D.pairingForFlight(this.ds, flightId);
    const legs = this.ds.flights
      .filter((x) => x.aircraft === f.aircraft && x.date === f.date && x.dep_utc > f.dep_utc)
      .sort((a, b) => a.dep_utc.localeCompare(b.dep_utc));
    let cum = delayMin;
    return this.ok(legs.map((l) => {
      const slackToThis = 0;
      cum = Math.max(0, cum - slackToThis);
      return {
        flight_id: l.flight_id, flight_no: l.flight_no, dep_utc: l.dep_utc, arr_utc: l.arr_utc,
        dep_station: l.dep_station, arr_station: l.arr_station,
        cumulative_delay_min: cum,
        same_pairing: !!p && p.days.some((d) => d.flights.includes(l.flight_id)),
      };
    }));
  }

  pairing(pairingId: string): Observable<PairingDetail> {
    const p = this.ds.pairingById.get(pairingId);
    if (!p) return this.ok(null as unknown as PairingDetail);
    const lastLeg = this.ds.flightById.get(p.days[0].flights.at(-1)!);
    return this.ok({
      pairing_id: p.pairing_id, aircraft: p.aircraft, days: p.days, crew: p.crew,
      overnight_station: p.days.length > 1 ? lastLeg?.arr_station ?? null : null,
    });
  }

  candidates(pairingId: string, role: string, calloutUtc: string, delayH?: number): Observable<CandidateResult> {
    return this.ok(D.coverCandidates(this.ds, pairingId, role, calloutUtc));
  }

  /* -------- crew -------- */
  crew(q: CrewQuery): Observable<CrewRow[]> {
    const date = q.date ?? this.ds.weekStart;
    let rows = this.ds.crew.map((c) => D.toCrewRow(this.ds, c, date));
    const reserveIds = new Set(this.ds.reserves.filter((r) => r.dates.includes(date)).map((r) => r.crew_id));
    switch (q.filter) {
      case 'needs_attention': rows = rows.filter((r) => r.attention.flag); break;
      case 'on_duty': rows = rows.filter((r) => r.on_duty); break;
      case 'off_duty': rows = rows.filter((r) => !r.on_duty && !reserveIds.has(r.crew_id)); break;
      case 'on_reserve': rows = rows.filter((r) => reserveIds.has(r.crew_id)); break;
    }
    if (q.role) rows = rows.filter((r) => r.rank === q.role);
    if (q.base) rows = rows.filter((r) => r.base === q.base);
    if (q.status) rows = rows.filter((r) => r.status === q.status);
    if (q.q) {
      const s = q.q.toLowerCase();
      rows = rows.filter((r) => r.crew_id.toLowerCase().includes(s) || r.name.toLowerCase().includes(s));
    }
    rows.sort((a, b) => Number(b.attention.flag) - Number(a.attention.flag) || a.crew_id.localeCompare(b.crew_id));
    return this.ok(rows);
  }

  crewDetail(crewId: string, date?: string): Observable<CrewDetail> {
    const c = this.ds.crewById.get(crewId);
    if (!c) return this.ok(null as unknown as CrewDetail);
    const onDate = date ?? this.ds.weekStart;
    const row = D.toCrewRow(this.ds, c, onDate);
    const clock = this.ds.dutyById.get(crewId);
    const res = this.ds.reserveById.get(crewId);
    return this.ok({
      ...row,
      seniority: c.seniority, reachability_minutes: c.reachability_minutes,
      duty_clock: this.buildDutyClock(crewId, onDate),
      certifications: D.certRows(this.ds, crewId, onDate),
      risk: {
        score: this.ds.riskById.get(crewId)?.disruption_risk_score ?? 0,
        drivers: this.ds.riskById.get(crewId)?.drivers ?? [],
      },
      reserve_window: res ? res.oncall_window_utc : null,
      assignments: (this.ds.pairingsByCrew.get(crewId) ?? []).flatMap((p) =>
        p.days.map((d) => ({
          pairing_id: p.pairing_id, date: d.date, flights: d.flights,
          report_utc: d.report_utc, release_utc: d.release_utc,
          role: p.crew.find((m) => m.crew_id === crewId)?.role ?? '',
        })),
      ).sort((a, b) => a.date.localeCompare(b.date)),
    });
  }

  crewLegality(crewId: string, pairingId: string, delayH?: number): Observable<RuleVerdict[]> {
    return this.ok(D.legalityVerdicts(this.ds, crewId, pairingId, delayH ?? 0));
  }

  dutyClock(crewId: string, date?: string): Observable<DutyClock> {
    return this.ok(this.buildDutyClock(crewId, date ?? this.ds.weekStart));
  }

  private buildDutyClock(crewId: string, date: string): DutyClock {
    const clock = this.ds.dutyById.get(crewId);
    const duty = clock?.duty_hours_7d ?? 0;
    const flt = clock?.flight_hours_28d ?? 0;
    const start = new Date(date + 'T00:00:00Z');
    start.setUTCDate(start.getUTCDate() - 6);
    const rest = clock?.last_rest_ended ?? null;
    return {
      crew_id: crewId, date,
      duty_hours_7d: round2(duty), duty_7d_headroom: round2(60 - duty),
      flight_hours_28d: round2(flt), flight_28d_headroom: round2(100 - flt),
      last_rest_ended: rest,
      rest_ok: rest ? (Date.parse(date + 'T00:00:00Z') - Date.parse(rest)) / 3_600_000 >= 12 : true,
      window: { start: start.toISOString().slice(0, 10), end: date },
    };
  }

  reserves(date?: string, base?: string, role?: string, coversReportUtc?: string): Observable<Reserve[]> {
    return this.ok(D.reserveRows(this.ds, date ?? this.ds.weekStart, base, role, coversReportUtc));
  }

  /* -------- alerts -------- */
  alerts(date?: string, status?: string, severity?: string, type?: string): Observable<Alert[]> {
    let list = D.buildAlerts(this.ds, date ?? this.ds.weekStart)
      .map((a) => ({ ...a, status: this.alertState.get(a.id) ?? a.status }));
    if (status) list = list.filter((a) => a.status === status);
    if (severity) list = list.filter((a) => a.severity === severity);
    if (type) list = list.filter((a) => a.type === type);
    return this.ok(list);
  }

  ackAlert(id: string): Observable<{ id: string; status: string }> {
    this.alertState.set(id, 'ack');
    return this.ok({ id, status: 'ack' });
  }
  resolveAlert(id: string, note?: string): Observable<{ id: string; status: string }> {
    this.alertState.set(id, 'resolved');
    return this.ok({ id, status: 'resolved' });
  }

  /* -------- sidebar -------- */
  summary(date: string): Observable<Summary> {
    return this.ok(D.buildSummary(this.ds, date));
  }
  riskSignals(threshold = 0): Observable<RiskSignal[]> {
    return this.ok(this.ds.risk
      .filter((r) => r.disruption_risk_score >= threshold)
      .sort((a, b) => b.disruption_risk_score - a.disruption_risk_score)
      .map((r) => ({
        crew_id: r.crew_id, name: this.ds.crewById.get(r.crew_id)?.name ?? r.crew_id,
        risk_score: r.disruption_risk_score, drivers: r.drivers,
      })));
  }

  /* -------- decisions -------- */
  postDecision(d: Omit<Decision, 'id' | 'created_utc'>): Observable<Decision> {
    const rec: Decision = { ...d, id: `DEC-${this.decisions.length + 1}`, created_utc: new Date().toISOString() };
    this.decisions.push(rec);
    return this.ok(rec);
  }
  getDecisions(): Observable<Decision[]> {
    return this.ok([...this.decisions].reverse());
  }
}

const round2 = (n: number): number => Math.round(n * 100) / 100;

const GLOSS: Record<string, string> = {
  'RULE-FDP-01': 'Max flight duty period is 13h, shrinking 30 min for every sector beyond the 2nd (4 sectors → 12.0h).',
  'RULE-DUTY-02': 'No more than 60 duty hours across any 7 consecutive UTC calendar days, inclusive of the duty date.',
  'RULE-FLT-03': 'No more than 100 block hours across any 28 consecutive UTC calendar days.',
  'RULE-REST-04': 'At least 12h of rest between a release and the next report — checked both sides of the new duty.',
  'RULE-QUAL-05': 'Crew must hold a current type rating for the aircraft (A320 or ATR72).',
  'RULE-CERT-06': 'Licence, medical and recurrent-training must all be valid on every duty date of the pairing.',
  'RULE-BASE-07': 'Reserve callouts are own-base only; covering from another base needs a deadhead (positioning + delay cost).',
};
