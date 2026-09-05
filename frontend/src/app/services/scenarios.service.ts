import { Injectable, inject, signal } from '@angular/core';
import { environment } from '../../environments/environment';
import { Option } from '../models/agent-events';

export interface ScenarioSummary {
  id: string;
  difficulty: string;
  title: string;
  tier: number;
  exercises: string[];
  prompt: string;
}

/** Local fallback so the scenario feed renders even with useMock + no backend. */
const LOCAL_SCENARIOS: ScenarioSummary[] = [
  { id: 'S1', difficulty: 'easy', title: 'ATR captain sick call', tier: 2, exercises: ['LEX', 'JUDGE'],
    prompt: 'Captain C-3231 calls in sick at 01:30Z on 16 Sep for pairing P-2224 (VT-DXE, 4 legs). Which flights are uncrewed and who covers?' },
  { id: 'S2', difficulty: 'medium', title: 'Flagship: C-1042 sick — 2-day pairing', tier: 3, exercises: ['LEX', 'RIPPLE', 'deadhead', 'JUDGE'],
    prompt: 'Captain C-1042 calls in sick at 05:00Z on 15 Sep for his 2-day pairing P-2291. Produce ranked resolution options with costs and reasoning.' },
  { id: 'S3', difficulty: 'medium', title: 'BLR station closure 08:00–14:00Z, 17 Sep', tier: 3, exercises: ['SANDBOX', 'RIPPLE'],
    prompt: 'BLR is closed to all departures and arrivals 08:00–14:00Z on 17 Sep. Outline the recovery plan across affected pairings.' },
  { id: 'S4', difficulty: 'medium-hard', title: 'Tech delay cascades into an FDP breach', tier: 3, exercises: ['SANDBOX', 'LEX', 'RIPPLE'],
    prompt: 'VT-DXA has a 90-minute technical delay before DX401 on 16 Sep. What should Crew Control do about the FDP breach?' },
  { id: 'S5', difficulty: 'medium', title: 'Certification lapse discovered pre-flight', tier: 3, exercises: ['LEX (CERT-06)'],
    prompt: "Compliance flags at 10:00Z on 18 Sep that C-5417's recurrent_training expired on 17 Sep. Resolve their 19 Sep VT-DXB assignment." },
  { id: 'S6', difficulty: 'hard', title: 'Two simultaneous captain sick calls', tier: 3, exercises: ['JOINT'],
    prompt: 'At 00:30Z on 18 Sep the captains of both VT-DXA (C-3940) and VT-DXB (C-1938) call in sick. Give the optimal joint crewing plan.' },
];

export const SEEDED_ASKS: string[] = [
  'Who is on reserve at BLR on 2026-09-15, and what are their on-call windows?',
  'Captain C-1042 called in sick for P-2291 on 15 Sep — who do I use?',
  'Captain C-1042 is out for P-2291. What should I do?',
  "What's the weather forecast at BLR tomorrow morning?",
];

/**
 * Scenario feed (S1–S6) and the policy-slider re-rank, both with local fallbacks.
 * Why: keeps `/scenarios` + `/rank` off the components and works with no backend.
 */
@Injectable({ providedIn: 'root' })
export class ScenariosService {
  readonly scenarios = signal<ScenarioSummary[]>(LOCAL_SCENARIOS);

  async load(): Promise<void> {
    if (environment.useMock) return;
    try {
      const res = await fetch(`${environment.apiBase}/api/v1/scenarios`);
      if (res.ok) this.scenarios.set(await res.json());
    } catch {
      /* keep local fallback */
    }
  }

  /** Policy-slider path: re-rank the current options with new weights, no LLM. */
  async rank(options: Option[], weights: Record<string, number>): Promise<Option[]> {
    if (environment.useMock) return localRank(options, weights);
    try {
      const res = await fetch(`${environment.apiBase}/api/v1/rank`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ options, weights }),
      });
      if (res.ok) return (await res.json()).options as Option[];
    } catch {
      /* fall through */
    }
    return localRank(options, weights);
  }
}

/** Same formula as api/mock.py::rank — keep them in sync. */
export function localRank(options: Option[], w: Record<string, number>): Option[] {
  const weights = { cost: 1, delay: 1, pool: 0.5, pairing: 0.8, fairness: 0.3, ...w };
  const score = (o: Option): number => {
    const cost = (o.cost_inr ?? 0) / 1000;
    const delay = o.delay_hours ?? 0;
    const poolHit = /reserve callout/i.test(o.action) ? 1 : 0;
    const blast = o.blast_radius ?? 0;
    return weights.cost * cost + weights.delay * delay * 5.4 + weights.pool * poolHit * 3 + weights.pairing * blast * 2;
  };
  const legal = options.filter((o) => o.legal).sort((a, b) => score(a) - score(b));
  const illegal = options.filter((o) => !o.legal);
  return [...legal, ...illegal].map((o, i) => ({ ...o, rank: i + 1, _score: Math.round(score(o) * 100) / 100 }));
}
