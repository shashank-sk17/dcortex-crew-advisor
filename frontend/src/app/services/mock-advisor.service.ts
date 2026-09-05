import { Injectable } from '@angular/core';
import { Observable, concatMap, delay, from, of } from 'rxjs';
import { AgentEvent } from '../models/agent-events';

type Beat = [number, AgentEvent];

/**
 * Scripted event streams matching the RECONCILED contract exactly.
 * The whole console — trace panel, rule trace, funnel, option cards, blast radius,
 * abstain card — is demo-able before the backend exists. Keep this in the build:
 * if the backend dies before the demo, flip environment.useMock back to true.
 */
@Injectable({ providedIn: 'root' })
export class MockAdvisorService {
  ask(question: string): Observable<AgentEvent> {
    const assign = question.match(/^Confirm assignment: (.+?) — (.+?) for ([^.]+)\.(?: Reason: (.+))?$/);
    let beats: Beat[];
    if (assign) {
      const [, crewId, action, ref, reason] = assign;
      beats = buildAssignBeats(crewId, action, ref, reason);
    } else {
      const q = question.toLowerCase();
      if (/what should i do|recommend|resolution options|produce ranked|c-1042 is out/.test(q)) {
        beats = TIER3;
      } else if (/immediately uncrewed|now uncrewed|which flights are uncovered/.test(q)) {
        beats = TIER2_IMPACT;
      } else if (/sick|cover p-2291|who do i (use|call)|if (captain |fo )?c-2087|breach|move .* onto/.test(q)) {
        beats = TIER2;
      } else if (/weather|forecast|metar|why did|last month|profit|passenger name|predict|likely to call/.test(q)) {
        beats = ABSTAIN;
      } else {
        beats = TIER1;
      }
    }
    return from(beats).pipe(concatMap(([ms, ev]) => of(ev).pipe(delay(ms))));
  }
}

/**
 * The chat's Accept/Modify buttons don't call a REST endpoint directly — they
 * send the choice to the agent as an instruction (`Confirm assignment: …`), same
 * as any other question, so the outcome comes back as a real streamed reply
 * instead of a client-fabricated string. A real backend would route this to a
 * `log_decision`-style tool that performs the same POST /decisions write
 * server-side while narrating the result. Modify's override reason rides along
 * on the same instruction (` Reason: …`) so the agent's reply can echo it back.
 */
function buildAssignBeats(crewId: string, action: string, ref: string, reason?: string): Beat[] {
  const prose = reason
    ? `Assigned — ${action}. Override reason: ${reason}. Recorded to the shift log. `
    : `Assigned — ${action}. Recorded to the shift log. `;
  const args: Record<string, unknown> = { crew_id: crewId, disruption_ref: ref };
  if (reason) args['note'] = reason;
  return [
    [100, { type: 'status', text: 'Recording the decision…' }],
    [200, { type: 'tool_call', id: 'a1', tool: 'log_decision', args }],
    [220, { type: 'tool_result', id: 'a1', tool: 'log_decision', ms: 8, summary: `${crewId} logged against ${ref}`, data: { logged: true } }],
    ...words(prose),
    [80, { type: 'done', elapsed_ms: 500, grounded: true }],
  ];
}

const words = (s: string, ms = 20): Beat[] =>
  s.split(/(?<= )/).map((w) => [ms, { type: 'token', text: w } as AgentEvent]);

const ALL7: string[] = [
  'RULE-FDP-01', 'RULE-DUTY-02', 'RULE-FLT-03', 'RULE-REST-04',
  'RULE-QUAL-05', 'RULE-CERT-06', 'RULE-BASE-07',
];

/* -------------------------------------------------------------------- Tier 1 */
const TIER1: Beat[] = [
  [120, { type: 'status', text: 'Resolving station BLR and date 2026-09-15…' }],
  [240, { type: 'tool_call', id: 't1', tool: 'lookup', args: { entity: 'reserve_pool', filters: { base: 'BLR', date: '2026-09-15' } } }],
  [380, { type: 'tool_result', id: 't1', tool: 'lookup', ms: 9, summary: '12 reserve crew on call at BLR on 15 Sep', data: { rows: 12, source: 'reserve_pool.json' } }],
  [200, {
    type: 'answer', tier: 1, intent: 'LOOKUP_RESERVES', entities: { station: 'BLR', date: '2026-09-15' },
    confidence: 'high', unknowns: [],
    citations: [{ kind: 'record', source: 'reserve_pool.json', id: 'BLR' }],
    narrative:
      'Twelve reserves are on call at BLR on 15 Sep — three Captains (C-3305, C-3310, C-3315), two First Officers, seven cabin crew. C-3305 covers only 00:00–05:30Z; C-3310 and C-3315 cover the daytime.',
    answer: {
      kind: 'lookup',
      title: 'Reserve crew on call — BLR, 15 Sep 2026',
      columns: ['Crew', 'Rank', 'On-call (UTC)', 'Reachable'],
      rows: [
        ['C-3305', 'Captain', '00:00–05:30', '—'],
        ['C-3310', 'Captain', '06:00–18:00', '45 min'],
        ['C-3311', 'First Officer', '06:00–18:00', '—'],
        ['C-3312', 'First Officer', '00:00–12:00', '—'],
        ['C-3315', 'Captain', '03:00–15:00', '—'],
        ['C-3316', 'First Officer', '03:00–15:00', '—'],
        ['C-2111', 'Senior Cabin Crew', '04:00–16:00', '—'],
        ['C-3677', 'Senior Cabin Crew', '04:00–16:00', '—'],
        ['C-5418', 'Cabin Crew', '04:00–16:00', '—'],
        ['C-1329', 'Cabin Crew', '04:00–16:00', '—'],
        ['C-2248', 'Cabin Crew', '04:00–16:00', '—'],
        ['C-4809', 'Cabin Crew', '00:00–12:00', '—'],
      ],
      count: 12,
      citations: ['reserve_pool.json', 'crew.json'],
    },
  }],
  ...words('Twelve reserves are on call at BLR on 15 Sep — three Captains, two First Officers, seven cabin crew. '),
  [80, { type: 'done', elapsed_ms: 1240, grounded: true }],
];

/* ------------------------------------------------------------- Tier 2 impact */
const TIER2_IMPACT: Beat[] = [
  [120, { type: 'status', text: 'Tracing pairing P-2291 for C-1042…' }],
  [240, { type: 'tool_call', id: 't1', tool: 'ripple', args: { event: { type: 'SICK_CREW', crew_id: 'C-1042', pairing_id: 'P-2291' } } }],
  [420, { type: 'tool_result', id: 't1', tool: 'ripple', ms: 19, summary: 'day 1: 3 legs uncrewed (486 pax); day 2: 3 legs at risk — overnights at DEL', data: { source: 'rosters.json + flights.json' } }],
  [180, { type: 'rule_check', rule_id: 'RULE-QUAL-05', subject: 'P-2291', status: 'NOT_APPLICABLE', detail: 'No substitute proposed yet — impact assessment only.' }],
  [200, {
    type: 'answer', tier: 2, intent: 'ASSESS_IMPACT', entities: { crew_id: 'C-1042', pairing_id: 'P-2291' },
    confidence: 'high', unknowns: [],
    citations: [{ kind: 'record', source: 'rosters.json', id: 'P-2291' }],
    narrative:
      'Three legs lose their Captain immediately — DX412, DX413, DX588 on 15 Sep (486 passengers). P-2291 is a two-day pairing overnighting at DEL, so day 2 (DX589/590/591 on 16 Sep) is also at risk: the cover must take the whole pairing.',
    answer: {
      kind: 'replacement',
      uncovered_flights: ['DX412-2026-09-15', 'DX413-2026-09-15', 'DX588-2026-09-15'],
      at_risk_flights: ['DX589-2026-09-16', 'DX590-2026-09-16', 'DX591-2026-09-16'],
      passengers_affected: 486, funnel: [], options: [], near_misses: [], excluded: [],
    },
  }],
  ...words('Three legs are uncrewed on 15 Sep — DX412, DX413, DX588, 486 passengers. Day 2 is at risk because the pairing overnights at DEL. '),
  [80, { type: 'done', elapsed_ms: 1180, grounded: true }],
];

/* ------------------------------------------------------ Tier 2 replacement */
const TIER2: Beat[] = [
  [120, { type: 'status', text: 'Tracing P-2291 and enumerating legal cover…' }],
  [240, { type: 'tool_call', id: 't1', tool: 'lookup', args: { entity: 'pairing', filters: { pairing_id: 'P-2291' } } }],
  [340, { type: 'tool_result', id: 't1', tool: 'lookup', ms: 6, summary: 'P-2291 — 2-day pairing, overnights at DEL', data: { aircraft: 'VT-DXC', days: 2, source: 'rosters.json' } }],
  [160, { type: 'tool_call', id: 't2', tool: 'ripple', args: { event: { type: 'SICK_CREW', crew_id: 'C-1042', pairing_id: 'P-2291' } } }],
  [420, { type: 'tool_result', id: 't2', tool: 'ripple', ms: 22, summary: '3 legs uncrewed day 1; 486 pax; day 2 orphaned at DEL', data: { uncovered: 3, at_risk: 3, pax: 486 } }],
  [160, { type: 'tool_call', id: 't3', tool: 'find_options', args: { pairing_id: 'P-2291', role: 'Captain', callout_utc: '2026-09-15T05:00:00Z' } }],
  [520, { type: 'tool_result', id: 't3', tool: 'find_options', ms: 41, summary: '150 crew → 6 legal (+2 near-miss); 6 blocked with traces', data: { evaluated: 32, legal: 6, near_miss: 2 } }],
  [180, { type: 'rule_check', rule_id: 'RULE-QUAL-05', subject: 'C-3310', status: 'PASS', detail: 'A320 rating valid; P-2291 is A320 throughout.' }],
  [140, { type: 'rule_check', rule_id: 'RULE-REST-04', subject: 'C-3310', status: 'PASS', margin: '4h10m spare', detail: 'Last release 14 Sep; report 15 Sep 06:00Z gives >12h rest.' }],
  [140, { type: 'rule_check', rule_id: 'RULE-BASE-07', subject: 'C-3310', status: 'PASS', detail: 'BLR own-base reserve callout; no deadhead cost.' }],
  [160, { type: 'rule_check', rule_id: 'RULE-DUTY-02', subject: 'C-2087', status: 'FAIL', margin: '1h20m over', detail: 'would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)', used: 61.33, limit: 60, headroom: -1.33, date: '2026-09-15' }],
  [140, { type: 'rule_check', rule_id: 'RULE-BASE-07', subject: 'C-3305', status: 'FAIL', detail: 'reserve on-call window 00:00-05:30Z does not cover required report 06:00Z' }],
  [200, {
    type: 'answer', tier: 2, intent: 'FIND_REPLACEMENT',
    entities: { crew_id: 'C-1042', pairing_id: 'P-2291', role: 'Captain', callout_utc: '2026-09-15T05:00:00Z' },
    confidence: 'high', unknowns: [],
    citations: [
      { kind: 'rule', id: 'RULE-DUTY-02' },
      { kind: 'rule', id: 'RULE-BASE-07' },
      { kind: 'record', source: 'reserve_pool.json', id: 'C-3310' },
    ],
    narrative:
      'Reserve Captain C-3310 is your cleanest option: BLR-based, A320-rated, on-call window covers the 06:00Z report, clears all seven rules with margin, ₹18,500. The obvious pick C-2087 is illegal — 1h20m over the 60h/7-day duty limit on day 1, still over on day 2. If no reserve were free, C-2210 out of DEL is legal via the DX402 deadhead at ₹41,200 (~3h delay to DX412) — far below the ₹250,000 to cancel one leg.',
    answer: {
      kind: 'replacement',
      uncovered_flights: ['DX412-2026-09-15', 'DX413-2026-09-15', 'DX588-2026-09-15'],
      at_risk_flights: ['DX589-2026-09-16', 'DX590-2026-09-16', 'DX591-2026-09-16'],
      passengers_affected: 486,
      funnel: [
        { stage: 'all_crew', count: 150 },
        { stage: 'role', count: 32, dropped: 118, reason: 'not Captain' },
        { stage: 'qualified', count: 21, dropped: 11, reason: 'RULE-QUAL-05 / status' },
        { stage: 'available', count: 12, dropped: 9, reason: 'duty conflict — already rostered' },
        { stage: 'legal', count: 6, dropped: 6, reason: 'rule breach — full trace attached' },
      ],
      options: [
        { action: 'Assign Captain C-3310 (reserve callout)', crew_id: 'C-3310', legal: true, rules_checked: ALL7, cost_inr: 18500, delay_hours: 0, rank: 1, cost_breakdown: { callout: 18500, positioning: 0, delay: 0 }, blast_radius: 0, coverage: 'all 6 flights', reachability_minutes: 45, reasoning: 'BLR-based reserve, A320-rated, on-call 06:00–18:00 covers the 06:00Z report. No deadhead, no delay.' },
        { action: 'Assign Captain C-1526 (day-off callout)', crew_id: 'C-1526', legal: true, rules_checked: ALL7, cost_inr: 24000, delay_hours: 0, rank: 2, cost_breakdown: { callout: 24000, positioning: 0, delay: 0 }, blast_radius: 0, coverage: 'all 6 flights', reasoning: 'Day-off callout — legal and clean, ₹5,500 more than the reserve.' },
        { action: 'Assign Captain C-3983 (day-off callout)', crew_id: 'C-3983', legal: true, rules_checked: ALL7, cost_inr: 24000, delay_hours: 0, rank: 3, cost_breakdown: { callout: 24000, positioning: 0, delay: 0 }, blast_radius: 0, coverage: 'all 6 flights', reasoning: 'Equivalent day-off callout.' },
      ],
      near_misses: [
        { action: 'Assign Captain C-2210 (reserve callout + deadhead from DEL)', crew_id: 'C-2210', legal: true, rules_checked: ALL7, cost_inr: 41200, delay_hours: 3, rank: 5, cost_breakdown: { callout: 18500, positioning: 6500, delay: 16200 }, blast_radius: 2, coverage: 'all 6 flights', unlock: 'legal via DX402 deadhead DEL→BLR — DX412 departs ~3h late', reasoning: 'DEL-based reserve, positioned on DX402 (arr 08:45Z), reports 09:00Z. ₹41,200 all-in vs ₹250,000 to cancel one leg.' },
      ],
      excluded: [
        { crew_id: 'C-2087', verdicts: [
          { rule_id: 'RULE-DUTY-02', status: 'FAIL', detail: 'would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)', used: 61.33, limit: 60, headroom: -1.33, date: '2026-09-15' },
          { rule_id: 'RULE-DUTY-02', status: 'FAIL', detail: 'would exceed 60h/7d by 1h05m on 2026-09-16 (total 61.08h)', used: 61.08, limit: 60, headroom: -1.08, date: '2026-09-16' },
        ]},
        { crew_id: 'C-3305', verdicts: [{ rule_id: 'RULE-BASE-07', status: 'FAIL', detail: 'reserve on-call window 00:00-05:30Z does not cover required report 06:00Z' }] },
        { crew_id: 'C-3315', verdicts: [{ rule_id: 'RULE-QUAL-05', status: 'FAIL', detail: 'no A320 rating' }] },
        { crew_id: 'C-2091', verdicts: [{ rule_id: 'RULE-QUAL-05', status: 'FAIL', detail: 'no A320 rating (ATR72 only)' }] },
      ],
    },
  }],
  ...words('Reserve Captain C-3310 is the cleanest cover — clears every rule, ₹18,500. C-2087 is 1h20m over the 7-day duty limit and is excluded. '),
  [80, { type: 'done', elapsed_ms: 2620, grounded: true }],
];

/* ---------------------------------------------------- Tier 3 consequence */
const TIER3: Beat[] = [
  [120, { type: 'status', text: 'Enumerating legal coverage options and blast radius…' }],
  [240, { type: 'tool_call', id: 't1', tool: 'ripple', args: { event: { type: 'SICK_CREW', crew_id: 'C-1042', pairing_id: 'P-2291' } } }],
  [420, { type: 'tool_result', id: 't1', tool: 'ripple', ms: 28, summary: 'blast radius: 6 nodes, 3 direct + 3 orphaned, 1 aircraft, 486 pax', data: { source: 'flights.json + rosters.json' } }],
  [160, { type: 'tool_call', id: 't2', tool: 'find_options', args: { pairing_id: 'P-2291', role: 'Captain', callout_utc: '2026-09-15T05:00:00Z' } }],
  [560, { type: 'tool_result', id: 't2', tool: 'find_options', ms: 44, summary: '6 legal options ranked by (legal, cost_inr, delay_hours)', data: { legal: 6 } }],
  [140, { type: 'rule_check', rule_id: 'RULE-BASE-07', subject: 'C-3310', status: 'PASS', detail: 'BLR-based reserve; no deadhead cost applied.' }],
  [120, { type: 'rule_check', rule_id: 'RULE-FDP-01', subject: 'C-3310', status: 'PASS', margin: 'spare', detail: '3 sectors day 1 → FDP limit 12.5h; duty 9.5h.' }],
  [120, { type: 'rule_check', rule_id: 'RULE-BASE-07', subject: 'C-2210', status: 'PASS', detail: 'DEL-based; deadhead ₹6,500 + 3h delay applied to option total.' }],
  [200, {
    type: 'answer', tier: 3, intent: 'RECOMMEND_RESOLUTION',
    entities: { crew_id: 'C-1042', pairing_id: 'P-2291', role: 'Captain' },
    confidence: 'high', unknowns: [],
    citations: [
      { kind: 'rule', id: 'RULE-BASE-07' },
      { kind: 'record', source: 'reserve_pool.json', id: 'C-3310' },
      { kind: 'record', source: 'costs.json', id: 'reserve_callout_pilot' },
    ],
    narrative:
      'Recommendation: call reserve Captain C-3310 (₹18,500). BLR-based, A320-rated, on-call window covers the 06:00Z report, clears all seven rules, and takes the full 2-day pairing so day 2 out of DEL is not orphaned. Fallback: C-1526 day-off callout at ₹24,000. Deadheading C-2210 from DEL (₹41,200, DX412 ~3h late) only if no BLR captain is available — still beats ₹250,000-per-leg cancellation.',
    answer: {
      kind: 'consequence',
      options: [
        { action: 'Assign Captain C-3310 (reserve callout)', crew_id: 'C-3310', legal: true, rules_checked: ALL7, cost_inr: 18500, delay_hours: 0, rank: 1, cost_breakdown: { callout: 18500, positioning: 0, delay: 0 }, blast_radius: 0, coverage: 'all 6 flights', reachability_minutes: 45, reasoning: 'BLR-based, A320-rated, reachable in 45 min. No deadhead, no delay, no knock-on.' },
        { action: 'Assign Captain C-1526 (day-off callout)', crew_id: 'C-1526', legal: true, rules_checked: ALL7, cost_inr: 24000, delay_hours: 0, rank: 2, cost_breakdown: { callout: 24000, positioning: 0, delay: 0 }, blast_radius: 0, coverage: 'all 6 flights', reasoning: 'Day-off callout — clean, ₹5,500 more than the reserve.' },
        { action: 'Assign Captain C-2210 (reserve callout + deadhead from DEL, first departure delayed ~3.0h)', crew_id: 'C-2210', legal: true, rules_checked: ALL7, cost_inr: 41200, delay_hours: 3, rank: 5, cost_breakdown: { callout: 18500, positioning: 6500, delay: 16200 }, blast_radius: 2, coverage: 'all 6 flights', unlock: 'legal via DX402 deadhead DEL→BLR', reasoning: 'Only if no BLR cover is free. ₹41,200 all-in, DX412 ~3h late, zero cancellations.' },
        { action: 'Cancel all 6 flights of the pairing', crew_id: null, legal: true, rules_checked: [], cost_inr: 1500000, delay_hours: 0, rank: 6, cost_breakdown: { cancellation: 1500000 }, blast_radius: 6, coverage: '0 flights', reasoning: 'Last resort. ₹250,000 × 6 legs, 486+ passengers stranded across two days.' },
      ],
      blast_radius: {
        nodes: 6, flights: 3, aircraft: 1, passengers: 486,
        edges: [
          { from: 'C-1042', to: 'DX412-2026-09-15', kind: 'direct' },
          { from: 'C-1042', to: 'DX413-2026-09-15', kind: 'direct' },
          { from: 'C-1042', to: 'DX588-2026-09-15', kind: 'direct' },
          { from: 'DX588-2026-09-15', to: 'DX589-2026-09-16', kind: 'orphaned_day2' },
          { from: 'DX589-2026-09-16', to: 'DX590-2026-09-16', kind: 'orphaned_day2' },
          { from: 'DX590-2026-09-16', to: 'DX591-2026-09-16', kind: 'orphaned_day2' },
          { from: 'P-2291', to: 'VT-DXC', kind: 'aircraft_rotation' },
        ],
      },
      expected_choice: { crew_id: 'C-3310', rank: 1 },
    },
  }],
  ...words('Recommendation: call reserve Captain C-3310 at ₹18,500 — clean on all seven rules and covers the full 2-day pairing. '),
  [80, { type: 'done', elapsed_ms: 3180, grounded: true }],
];

/* --------------------------------------------------------------- Abstain */
const ABSTAIN: Beat[] = [
  [120, { type: 'status', text: 'Checking whether the dataset can answer this…' }],
  [300, { type: 'tool_call', id: 't1', tool: 'resolve_intent', args: { question: '…' } }],
  [420, { type: 'tool_result', id: 't1', tool: 'resolve_intent', ms: 12, summary: 'no tool covers this question; required fields absent from the dataset', data: { matched_tools: [], source: 'schema registry' } }],
  [200, {
    type: 'abstain',
    reason: "I can't answer that reliably. Nothing in the provided dataset supports it, and I will not infer a value.",
    needed: [
      'A live weather / METAR feed (not in the dataset)',
      'Operational history beyond the 7-day schedule window (2026-09-14 → 2026-09-20)',
      'Passenger-level records — only aggregate seat counts are provided',
      'A disruption-prediction model — risk_signals.json is a provided input, not something this advisor computes',
    ],
  }],
  [80, { type: 'done', elapsed_ms: 900, grounded: true }],
];
