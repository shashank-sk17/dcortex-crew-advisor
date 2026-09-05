import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';
import {
  Alert, CandidateResult, CrewDetail, CrewQuery, CrewRow, Decision, DownstreamLeg,
  DutyClock, FlightDetail, FlightQuery, FlightRow, Meta, PairingDetail, Reserve, RiskSignal,
  RuleDef, RuleVerdict, Summary,
} from './api.types';

/**
 * The contract both MockApiService and HttpApiService satisfy.
 * Components inject `API` (the token) and never know which one they got.
 * Swapping is one line in app.config.ts, driven by environment.useMock.
 */
export interface ApiPort {
  meta(): Observable<Meta>;
  rules(): Observable<RuleDef[]>;
  costs(): Observable<Record<string, unknown>>;

  flights(q: FlightQuery): Observable<FlightRow[]>;
  flight(flightId: string): Observable<FlightDetail>;
  downstream(flightId: string, delayMin?: number): Observable<DownstreamLeg[]>;
  pairing(pairingId: string): Observable<PairingDetail>;
  candidates(pairingId: string, role: string, calloutUtc: string, delayH?: number): Observable<CandidateResult>;

  crew(q: CrewQuery): Observable<CrewRow[]>;
  crewDetail(crewId: string, date?: string): Observable<CrewDetail>;
  crewLegality(crewId: string, pairingId: string, delayH?: number): Observable<RuleVerdict[]>;
  dutyClock(crewId: string, date?: string): Observable<DutyClock>;
  reserves(date?: string, base?: string, role?: string, coversReportUtc?: string): Observable<Reserve[]>;

  alerts(date?: string, status?: string, severity?: string, type?: string): Observable<Alert[]>;
  ackAlert(id: string): Observable<{ id: string; status: string }>;
  resolveAlert(id: string, note?: string): Observable<{ id: string; status: string }>;

  summary(date: string): Observable<Summary>;
  riskSignals(threshold?: number): Observable<RiskSignal[]>;

  postDecision(d: Omit<Decision, 'id' | 'created_utc'>): Observable<Decision>;
  getDecisions(): Observable<Decision[]>;
}

export const API = new InjectionToken<ApiPort>('API');
