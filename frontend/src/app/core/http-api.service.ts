import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import {
  Alert, CandidateResult, CrewDetail, CrewQuery, CrewRow, Decision, DownstreamLeg,
  DutyClock, FlightDetail, FlightQuery, FlightRow, Meta, PairingDetail, Reserve, RiskSignal,
  RuleDef, RuleVerdict, Summary,
} from './api.types';
import { ApiPort } from './api.port';

/**
 * The real transport. Mirrors MockApiService method-for-method so ApiService
 * can swap between them on `environment.useMock` with no caller changes.
 * Paths are docs/REST_API_v1.md.
 */
@Injectable({ providedIn: 'root' })
export class HttpApiService implements ApiPort {
  private http = inject(HttpClient);
  private base = `${environment.apiBase}/api/v1`;

  private params(o: Record<string, string | number | undefined>): HttpParams {
    let p = new HttpParams();
    for (const [k, v] of Object.entries(o)) if (v !== undefined && v !== '') p = p.set(k, String(v));
    return p;
  }

  meta(): Observable<Meta> { return this.http.get<Meta>(`${this.base}/meta`); }
  rules(): Observable<RuleDef[]> { return this.http.get<RuleDef[]>(`${this.base}/rules`); }
  costs(): Observable<Record<string, unknown>> { return this.http.get<Record<string, unknown>>(`${this.base}/costs`); }

  flights(q: FlightQuery): Observable<FlightRow[]> {
    return this.http.get<FlightRow[]>(`${this.base}/flights`, { params: this.params({ ...q }) });
  }
  flight(id: string): Observable<FlightDetail> { return this.http.get<FlightDetail>(`${this.base}/flights/${id}`); }
  downstream(id: string, delayMin?: number): Observable<DownstreamLeg[]> {
    return this.http.get<DownstreamLeg[]>(`${this.base}/flights/${id}/downstream`, { params: this.params({ delay_min: delayMin }) });
  }
  pairing(id: string): Observable<PairingDetail> { return this.http.get<PairingDetail>(`${this.base}/pairings/${id}`); }
  candidates(pairingId: string, role: string, calloutUtc: string, delayH?: number): Observable<CandidateResult> {
    return this.http.get<CandidateResult>(`${this.base}/pairings/${pairingId}/candidates`, {
      params: this.params({ role, callout_utc: calloutUtc, delay_h: delayH }),
    });
  }

  crew(q: CrewQuery): Observable<CrewRow[]> {
    return this.http.get<CrewRow[]>(`${this.base}/crew`, { params: this.params({ ...q }) });
  }
  crewDetail(id: string, date?: string): Observable<CrewDetail> {
    return this.http.get<CrewDetail>(`${this.base}/crew/${id}`, { params: this.params({ date }) });
  }
 
  crewLegality(id: string, pairingId: string, delayH?: number): Observable<RuleVerdict[]> {
    return this.http.get<RuleVerdict[]>(`${this.base}/crew/${id}/legality`, {
      params: this.params({ pairing_id: pairingId, delay_h: delayH }),
    });
  }
  dutyClock(id: string, date?: string): Observable<DutyClock> {
    return this.http.get<DutyClock>(`${this.base}/crew/${id}/duty-clock`, { params: this.params({ date }) });
  }
  reserves(date?: string, base?: string, role?: string, coversReportUtc?: string): Observable<Reserve[]> {
    return this.http.get<Reserve[]>(`${this.base}/reserves`, {
      params: this.params({ date, base, role, covers_report_utc: coversReportUtc }),
    });
  }

  alerts(date?: string, status?: string, severity?: string, type?: string): Observable<Alert[]> {
    return this.http.get<Alert[]>(`${this.base}/alerts`, { params: this.params({ date, status, severity, type }) });
  }
  ackAlert(id: string): Observable<{ id: string; status: string }> {
    return this.http.post<{ id: string; status: string }>(`${this.base}/alerts/${id}/ack`, {});
  }
  resolveAlert(id: string, note?: string): Observable<{ id: string; status: string }> {
    return this.http.post<{ id: string; status: string }>(`${this.base}/alerts/${id}/resolve`, { note });
  }

  summary(date: string): Observable<Summary> {
    return this.http.get<Summary>(`${this.base}/summary`, { params: this.params({ date }) });
  }
  riskSignals(threshold?: number): Observable<RiskSignal[]> {
    return this.http.get<RiskSignal[]>(`${this.base}/risk-signals`, { params: this.params({ threshold }) });
  }

  postDecision(d: Omit<Decision, 'id' | 'created_utc'>): Observable<Decision> {
    return this.http.post<Decision>(`${this.base}/decisions`, d);
  }
  getDecisions(): Observable<Decision[]> {
    return this.http.get<Decision[]>(`${this.base}/decisions`);
  }
}

// crew assignments
// notifications