/**
 * Deterministic derivations for the mock: delay_rank, attention flags, alerts,
 * summary counts, cover candidates. Computed from the real dataset rows.
 *
 * Not a re-implementation of `core/` legality — the flagship legality/candidate
 * flows come through the advisor stream with answer-key fixtures. This is enough
 * for the board, the crew view and the alert panel to be real and consistent.
 */
import {
  Dataset, RawCrew, RawFlight, RawPairing,
} from './dataset';
import {
  Alert, Attention, CandidateResult, CrewRow, DelayRank, FlightRow,
  FlightStatus, Option, Reserve, RuleVerdict, Summary,
} from '../api.types';

const MIN = 60_000;
const parse = (s: string): number => Date.parse(s);
const hhmmToMin = (s: string): number => {
  const [h, m] = s.split(':').map(Number);
  return h * 60 + m;
};

export function pairingForFlight(ds: Dataset, flightId: string): RawPairing | null {
  for (const p of ds.rosters.pairings) {
    for (const d of p.days) if (d.flights.includes(flightId)) return p;
  }
  return null;
}

function pairingDayForFlight(p: RawPairing, flightId: string) {
  return p.days.find((d) => d.flights.includes(flightId)) ?? null;
}

function sectorsFdpLimitHours(sectors: number): number {
  return 13.0 - 0.5 * Math.max(0, sectors - 2);
}

/** duty hours already accrued in the rolling 7-day summary (approximation for the board). */
export function duty7d(ds: Dataset, crewId: string): number {
  return ds.dutyById.get(crewId)?.duty_hours_7d ?? 0;
}
export function flight28d(ds: Dataset, crewId: string): number {
  return ds.dutyById.get(crewId)?.flight_hours_28d ?? 0;
}

/* ------------------------------------------------------------ delay rank */

export function delayRank(ds: Dataset, f: RawFlight): {
  rank: DelayRank; score: number; reasons: string[];
  slack: number | null; downstream: number; fdpHeadroom: number | null;
} {
  const sameTailToday = ds.flights
    .filter((x) => x.aircraft === f.aircraft && x.date === f.date)
    .sort((a, b) => parse(a.dep_utc) - parse(b.dep_utc));
  const idx = sameTailToday.findIndex((x) => x.flight_id === f.flight_id);
  const next = idx >= 0 && idx < sameTailToday.length - 1 ? sameTailToday[idx + 1] : null;
  const downstream = idx >= 0 ? sameTailToday.length - 1 - idx : 0;
  const slack = next ? Math.round((parse(next.dep_utc) - parse(f.arr_utc)) / MIN) : null;

  const p = pairingForFlight(ds, f.flight_id);
  let fdpHeadroom: number | null = null;
  let overnightAway = false;
  if (p) {
    const day = pairingDayForFlight(p, f.flight_id);
    if (day) {
      const sectors = day.flights.length;
      const dutyH = (parse(day.release_utc) - parse(day.report_utc)) / (60 * MIN);
      fdpHeadroom = Math.round((sectorsFdpLimitHours(sectors) - dutyH) * 60);
    }
    const dayIdx = p.days.findIndex((d) => d.flights.includes(f.flight_id));
    overnightAway = p.days.length > 1 && dayIdx === 0;
  }

  const reasons: string[] = [];
  let score = 15;
  if (slack != null) {
    if (slack < 30) { reasons.push(`tail slack ${slack}m < 30m`); score += 45; }
    else if (slack < 60) { reasons.push(`tail slack ${slack}m < 60m`); score += 28; }
    else if (slack < 120) { reasons.push(`tail slack ${slack}m`); score += 14; }
  }
  if (fdpHeadroom != null) {
    if (fdpHeadroom < 30) { reasons.push(`crew FDP headroom ${fdpHeadroom}m`); score += 40; }
    else if (fdpHeadroom < 60) { reasons.push(`crew FDP headroom ${fdpHeadroom}m`); score += 20; }
  }
  if (overnightAway) { reasons.push('pairing overnights away from base (day-2 orphan risk)'); score += 25; }
  if (downstream >= 4) { reasons.push(`${downstream} downstream legs on the tail today`); score += 22; }
  else if (downstream >= 2) { reasons.push(`${downstream} downstream legs`); score += 10; }

  score = Math.min(100, score);
  let rank: DelayRank = 'low';
  if ((slack != null && slack < 30) || (fdpHeadroom != null && fdpHeadroom < 30) || overnightAway || downstream >= 4) rank = 'critical';
  else if ((slack != null && slack < 60) || (fdpHeadroom != null && fdpHeadroom < 60) || downstream >= 2) rank = 'high';
  else if ((slack != null && slack < 120) || downstream === 1) rank = 'medium';
  if (!reasons.length) reasons.push('ample slack / last leg of the day');

  return { rank, score, reasons, slack, downstream, fdpHeadroom };
}

export function toFlightRow(ds: Dataset, f: RawFlight): FlightRow {
  const d = delayRank(ds, f);
  const status: FlightStatus = d.rank === 'critical' ? 'at_risk' : 'scheduled';
  return {
    flight_id: f.flight_id, flight_no: f.flight_no, date: f.date,
    dep_station: f.dep_station, arr_station: f.arr_station, dep_utc: f.dep_utc, arr_utc: f.arr_utc,
    aircraft: f.aircraft, aircraft_type: f.aircraft_type, seats: f.seats,
    pairing_id: pairingForFlight(ds, f.flight_id)?.pairing_id ?? null,
    status,
    delay_rank: d.rank, delay_rank_score: d.score, delay_rank_reasons: d.reasons,
    slack_minutes: d.slack, downstream_count: d.downstream, crew_fdp_headroom_min: d.fdpHeadroom,
    basis: ['flights.json', 'rosters.json', 'rules.json'],
  };
}

/* -------------------------------------------------------------- attention */

export function certRows(ds: Dataset, crewId: string, onDate: string) {
  const day = Date.parse(onDate + 'T00:00:00Z');
  return (ds.certsByCrew.get(crewId) ?? []).map((c) => {
    const to = Date.parse(c.valid_to + 'T00:00:00Z');
    const days = Math.round((to - day) / (24 * 60 * MIN));
    return {
      type: c.cert_type, valid_from: c.valid_from, valid_to: c.valid_to,
      days_to_expiry: days, expiring_soon: days >= 0 && days <= 3,
    };
  });
}

export function attention(ds: Dataset, crew: RawCrew, onDate: string): Attention {
  const reasons: string[] = [];
  const clock = ds.dutyById.get(crew.crew_id);
  if (clock) {
    const dutyHead = 60 - clock.duty_hours_7d;
    const fltHead = 100 - clock.flight_hours_28d;
    if (dutyHead < 3) reasons.push(`RULE-DUTY-02 headroom ${dutyHead.toFixed(1)}h < 3h`);
    if (fltHead < 5) reasons.push(`RULE-FLT-03 headroom ${fltHead.toFixed(1)}h < 5h`);
  }
  for (const c of certRows(ds, crew.crew_id, onDate)) {
    if (c.expiring_soon) reasons.push(`${c.type} expires ${c.valid_to} (${c.days_to_expiry}d)`);
    if (c.days_to_expiry < 0) reasons.push(`${c.type} EXPIRED ${c.valid_to}`);
  }
  if (ds.rosters.flagged_exceptions.some((x) => x.crew_id === crew.crew_id)) {
    reasons.push('flagged roster exception');
  }
  const risk = ds.riskById.get(crew.crew_id)?.disruption_risk_score ?? 0;
  if (risk >= 0.7) reasons.push(`disruption-risk ${risk.toFixed(2)} ≥ 0.70`);
  return { flag: reasons.length > 0, reasons };
}

/** Is this crew mid-duty at the snapshot instant / on the given date? */
export function onDuty(ds: Dataset, crewId: string, onDate: string): boolean {
  const pairings = ds.pairingsByCrew.get(crewId) ?? [];
  return pairings.some((p) => p.days.some((d) => d.date === onDate));
}

export function nextReport(ds: Dataset, crewId: string, fromDate: string): string | null {
  const from = Date.parse(fromDate + 'T00:00:00Z');
  const reports = (ds.pairingsByCrew.get(crewId) ?? [])
    .flatMap((p) => p.days.map((d) => d.report_utc))
    .filter((r) => Date.parse(r) >= from)
    .sort();
  return reports[0] ?? null;
}

export function toCrewRow(ds: Dataset, c: RawCrew, onDate: string): CrewRow {
  const clock = ds.dutyById.get(c.crew_id);
  const duty = clock?.duty_hours_7d ?? 0;
  const pairing = (ds.pairingsByCrew.get(c.crew_id) ?? []).find((p) => p.days.some((d) => d.date === onDate));
  return {
    crew_id: c.crew_id, name: c.name, rank: c.rank, base: c.base, ratings: c.ratings, status: c.status,
    on_duty: onDuty(ds, c.crew_id, onDate),
    current_assignment: { pairing_id: pairing?.pairing_id ?? null, flight_id: null },
    next_report_utc: nextReport(ds, c.crew_id, onDate),
    duty_7d: round2(duty), duty_7d_headroom: round2(60 - duty),
    disruption_risk_score: ds.riskById.get(c.crew_id)?.disruption_risk_score ?? 0,
    attention: attention(ds, c, onDate),
    basis: ['duty_clocks.json', 'certifications.json', 'risk_signals.json'],
  };
}

/* ---------------------------------------------------------------- alerts */

export function buildAlerts(ds: Dataset, onDate: string): Alert[] {
  const out: Alert[] = [];
  let n = 1;
  const id = () => `AL-${String(n++).padStart(3, '0')}`;
  const stamp = ds.snapshotUtc;

  // ROSTER_EXCEPTION
  for (const x of ds.rosters.flagged_exceptions) {
    out.push({
      id: id(), type: 'ROSTER_EXCEPTION', severity: 'critical',
      subject: { kind: 'crew', id: x.crew_id },
      title: `${x.crew_id}: roster exception on ${x.date}`,
      detail: x.note, created_utc: stamp, status: 'open',
      suggested_action: { label: 'Resolve assignment', ask_prompt: `${x.crew_id} has a ${x.rule} exception on ${x.date}. Resolve it.`, deep_link: `/crew/${x.crew_id}` },
      payload: null,
    });
  }

  // CERT_EXPIRING (<= 3 days from onDate) and DUTY_LIMIT_NEAR (< 3h headroom)
  for (const c of ds.crew) {
    for (const cert of certRows(ds, c.crew_id, onDate)) {
      if (cert.days_to_expiry >= 0 && cert.days_to_expiry <= 3) {
        out.push({
          id: id(), type: 'CERT_EXPIRING', severity: cert.days_to_expiry <= 1 ? 'critical' : 'warning',
          subject: { kind: 'crew', id: c.crew_id },
          title: `${c.crew_id} ${cert.type} expires ${cert.valid_to}`,
          detail: `${cert.days_to_expiry} day(s) of validity left as of ${onDate}.`,
          created_utc: stamp, status: 'open',
          suggested_action: { label: 'Open crew', deep_link: `/crew/${c.crew_id}` }, payload: null,
        });
      }
    }
    const clock = ds.dutyById.get(c.crew_id);
    if (clock) {
      const head = 60 - clock.duty_hours_7d;
      if (head < 3 && onDuty(ds, c.crew_id, onDate)) {
        out.push({
          id: id(), type: 'DUTY_LIMIT_NEAR', severity: head < 1 ? 'critical' : 'warning',
          subject: { kind: 'crew', id: c.crew_id },
          title: `${c.crew_id} within ${head.toFixed(1)}h of the 60h/7d limit`,
          detail: `Accrued ${clock.duty_hours_7d.toFixed(2)}h in the last 7 days.`,
          created_utc: stamp, status: 'open',
          suggested_action: { label: 'Ask the advisor', ask_prompt: `${c.crew_id} is near the duty limit — what are my options?`, deep_link: `/crew/${c.crew_id}` },
          payload: null,
        });
      }
    }
  }

  // FLIGHT_AT_RISK — critical delay_rank flights on the date
  for (const f of ds.flights.filter((f) => f.date === onDate)) {
    const d = delayRank(ds, f);
    if (d.rank === 'critical') {
      out.push({
        id: id(), type: 'FLIGHT_AT_RISK', severity: 'warning',
        subject: { kind: 'flight', id: f.flight_id },
        title: `${f.flight_no} ${f.dep_station}→${f.arr_station} — critical delay rank`,
        detail: d.reasons.join('; '),
        created_utc: stamp, status: 'open',
        suggested_action: { label: 'Show impact', deep_link: `/board?flight=${f.flight_id}` }, payload: null,
      });
    }
  }

  // RESERVE_POOL_LOW — a base+role with <= 1 reserve on the date
  const poolCounts = reservePoolByBaseRole(ds, onDate);
  for (const [key, count] of Object.entries(poolCounts)) {
    if (count <= 1) {
      const [base, role] = key.split('|');
      out.push({
        id: id(), type: 'RESERVE_POOL_LOW', severity: count === 0 ? 'critical' : 'info',
        subject: { kind: 'reserve_pool', id: key },
        title: `${role} reserves at ${base}: ${count} on call`,
        detail: `Thin cover for ${role} at ${base} on ${onDate}.`,
        created_utc: stamp, status: 'open', suggested_action: null, payload: null,
      });
    }
  }

  const sev = { critical: 0, warning: 1, info: 2 } as const;
  return out.sort((a, b) => sev[a.severity] - sev[b.severity]);
}

function roleClass(rank: string): 'pilot' | 'cabin' {
  return rank === 'Captain' || rank === 'First Officer' ? 'pilot' : 'cabin';
}

export function reservePoolByBaseRole(ds: Dataset, onDate: string): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of ds.reserves) {
    if (!r.dates.includes(onDate)) continue;
    const rank = ds.crewById.get(r.crew_id)?.rank ?? 'Cabin Crew';
    const key = `${r.base}|${rank}`;
    out[key] = (out[key] ?? 0) + 1;
  }
  return out;
}

/* --------------------------------------------------------------- summary */

export function buildSummary(ds: Dataset, onDate: string): Summary {
  const dayFlights = ds.flights.filter((f) => f.date === onDate);
  const ranks = dayFlights.map((f) => delayRank(ds, f).rank);
  const onDutyCrew = ds.crew.filter((c) => onDuty(ds, c.crew_id, onDate));
  const reserveCrew = ds.reserves.filter((r) => r.dates.includes(onDate));
  const needAtt = ds.crew.filter((c) => attention(ds, c, onDate).flag).length;
  const alerts = buildAlerts(ds, onDate);

  return {
    date: onDate,
    crew: {
      on_duty: onDutyCrew.length,
      off_duty: ds.crew.length - onDutyCrew.length - reserveCrew.length,
      reserve: reserveCrew.length,
      needs_attention: needAtt,
    },
    flights: {
      total: dayFlights.length,
      on_time: ranks.filter((r) => r === 'low').length,
      at_risk: ranks.filter((r) => r === 'critical').length,
      delayed: ranks.filter((r) => r === 'high').length,
      cancelled: 0,
    },
    alerts: {
      critical: alerts.filter((a) => a.severity === 'critical').length,
      warning: alerts.filter((a) => a.severity === 'warning').length,
    },
    reserves: { by_base_role: reservePoolByBaseRole(ds, onDate), depleted: [] },
    aircraft: { in_service: new Set(dayFlights.map((f) => f.aircraft)).size, aog: 0 },
    stations: { closures: [] },
  };
}

/* ------------------------------------------------------------ candidates */

/** Deterministic cover shortlist from the reserve pool — the flight-detail panel. */
export function coverCandidates(
  ds: Dataset, pairingId: string, role: string, calloutUtc: string,
): CandidateResult {
  const p = ds.pairingById.get(pairingId);
  const reportUtc = p?.days[0]?.report_utc ?? calloutUtc;
  const reportMin = new Date(reportUtc).getUTCHours() * 60 + new Date(reportUtc).getUTCMinutes();
  const type = p ? ds.flightById.get(p.days[0].flights[0])?.aircraft_type ?? 'A320' : 'A320';

  const pilots = ds.reserves.filter((r) => {
    const c = ds.crewById.get(r.crew_id);
    return c?.rank === role;
  });

  const options: Option[] = [];
  const excluded: { crew_id: string; verdicts: RuleVerdict[] }[] = [];
  const near: Option[] = [];

  for (const r of pilots) {
    const c = ds.crewById.get(r.crew_id)!;
    const rated = c.ratings.includes(type);
    const winStart = hhmmToMin(r.oncall_window_utc.start);
    const winEnd = hhmmToMin(r.oncall_window_utc.end);
    const covers = reportMin >= winStart && reportMin <= winEnd;
    const cost = roleClass(role) === 'pilot' ? ds.costs.reserve_callout_pilot : ds.costs.reserve_callout_cabin;

    if (!rated) {
      excluded.push({ crew_id: r.crew_id, verdicts: [{ rule_id: 'RULE-QUAL-05', status: 'FAIL', detail: `no ${type} rating` }] });
      continue;
    }
    if (r.base !== (p ? ds.flightById.get(p.days[0].flights[0])?.dep_station : 'BLR')) {
      near.push({
        action: `Assign ${c.rank} ${c.crew_id} (deadhead from ${r.base})`, crew_id: c.crew_id, legal: true,
        rules_checked: ALL7, cost_inr: cost + ds.costs.deadhead_positioning, delay_hours: 3, rank: 0,
        cost_breakdown: { callout: cost, positioning: ds.costs.deadhead_positioning, delay: 3 * ds.costs.delay_cost_per_duty_hour },
        unlock: `legal via deadhead from ${r.base}`, reasoning: `Out-of-base reserve; positioning + delay apply.`,
      });
      continue;
    }
    if (!covers) {
      excluded.push({ crew_id: r.crew_id, verdicts: [{ rule_id: 'RULE-BASE-07', status: 'FAIL', detail: `reserve on-call window ${r.oncall_window_utc.start}-${r.oncall_window_utc.end}Z does not cover required report ${fmtHHMM(reportMin)}Z` }] });
      continue;
    }
    options.push({
      action: `Assign ${c.rank} ${c.crew_id} (reserve callout)`, crew_id: c.crew_id, legal: true,
      rules_checked: ALL7, cost_inr: cost, delay_hours: 0, rank: 0,
      cost_breakdown: { callout: cost, positioning: 0, delay: 0 }, blast_radius: 0, coverage: 'full pairing',
      reachability_minutes: c.reachability_minutes, reasoning: `${r.base} own-base reserve, ${type}-rated, window covers the report.`,
    });
  }

  options.sort((a, b) => a.cost_inr - b.cost_inr).forEach((o, i) => (o.rank = i + 1));
  near.forEach((o, i) => (o.rank = options.length + i + 1));

  const roleCount = ds.crew.filter((c) => c.rank === role).length;
  const funnel = [
    { stage: 'all_crew', count: ds.crew.length },
    { stage: 'role', count: roleCount, dropped: ds.crew.length - roleCount, reason: `not ${role}` },
    { stage: 'reserve_or_free', count: pilots.length, dropped: roleCount - pilots.length, reason: 'not on reserve / already rostered' },
    { stage: 'legal', count: options.length, dropped: pilots.length - options.length, reason: 'rule breach — see excluded' },
  ];

  return {
    pairing_id: pairingId, role, callout_utc: calloutUtc,
    funnel, options, near_misses: near, excluded,
    basis: ['reserve_pool.json', 'crew.json', 'costs.json', 'rules.json'],
  };
}

const ALL7 = ['RULE-FDP-01', 'RULE-DUTY-02', 'RULE-FLT-03', 'RULE-REST-04', 'RULE-QUAL-05', 'RULE-CERT-06', 'RULE-BASE-07'];
const round2 = (n: number): number => Math.round(n * 100) / 100;
const fmtHHMM = (min: number): string =>
  `${String(Math.floor(min / 60)).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`;

/** Lightweight 7-rule verdicts for "can this crew cover this pairing". */
export function legalityVerdicts(ds: Dataset, crewId: string, pairingId: string, delayH = 0): RuleVerdict[] {
  const c = ds.crewById.get(crewId);
  const p = ds.pairingById.get(pairingId);
  const out: RuleVerdict[] = [];
  if (!c || !p) return out;

  const type = ds.flightById.get(p.days[0].flights[0])?.aircraft_type ?? 'A320';
  const day0 = p.days[0];
  const sectors = day0.flights.length;
  const dutyH = (Date.parse(day0.release_utc) - Date.parse(day0.report_utc)) / 3_600_000 + delayH;
  const fdpLimit = sectorsFdpLimitHours(sectors);
  out.push({
    rule_id: 'RULE-FDP-01',
    status: dutyH <= fdpLimit + 1e-6 ? 'PASS' : 'FAIL',
    detail: `${dutyH.toFixed(2)}h duty vs ${fdpLimit.toFixed(1)}h limit (${sectors} sectors)`,
    used: round2(dutyH), limit: fdpLimit, headroom: round2(fdpLimit - dutyH), date: day0.date,
  });

  const clock = ds.dutyById.get(crewId);
  const duty7 = (clock?.duty_hours_7d ?? 0) + dutyH;
  out.push({
    rule_id: 'RULE-DUTY-02',
    status: duty7 <= 60 + 1e-6 ? 'PASS' : 'FAIL',
    detail: `${duty7.toFixed(2)}h / 60h in the 7 days to ${day0.date}`,
    used: round2(duty7), limit: 60, headroom: round2(60 - duty7), date: day0.date,
  });

  const flt28 = (clock?.flight_hours_28d ?? 0) + (dutyH * 0.72);
  out.push({
    rule_id: 'RULE-FLT-03',
    status: flt28 <= 100 + 1e-6 ? 'PASS' : 'FAIL',
    detail: `~${flt28.toFixed(1)}h / 100h in the 28 days to ${day0.date}`,
    used: round2(flt28), limit: 100, headroom: round2(100 - flt28), date: day0.date,
  });

  const restH = clock?.last_rest_ended
    ? (Date.parse(day0.report_utc) - Date.parse(clock.last_rest_ended)) / 3_600_000
    : 24;
  out.push({
    rule_id: 'RULE-REST-04',
    status: restH >= 12 ? 'PASS' : 'FAIL',
    detail: `${restH.toFixed(1)}h rest before report (min 12h)`,
    used: round2(restH), limit: 12, headroom: round2(restH - 12),
  });

  out.push({
    rule_id: 'RULE-QUAL-05',
    status: c.ratings.includes(type) ? 'PASS' : 'FAIL',
    detail: c.ratings.includes(type) ? `${type} rating valid` : `no ${type} rating (holds ${c.ratings.join('/')})`,
  });

  const certBad = (ds.certsByCrew.get(crewId) ?? []).filter(
    (ct) => Date.parse(ct.valid_to + 'T00:00:00Z') < Date.parse(p.days.at(-1)!.date + 'T00:00:00Z'),
  );
  out.push({
    rule_id: 'RULE-CERT-06',
    status: certBad.length ? 'FAIL' : 'PASS',
    detail: certBad.length ? `${certBad.map((x) => x.cert_type).join(', ')} invalid on a duty date` : 'all certifications valid on every duty date',
  });

  const p0Station = ds.flightById.get(day0.flights[0])?.dep_station;
  out.push({
    rule_id: 'RULE-BASE-07',
    status: c.base === p0Station ? 'PASS' : 'NOT_APPLICABLE',
    detail: c.base === p0Station ? `${c.base} own-base` : `based ${c.base}, pairing starts ${p0Station} — deadhead cost applies`,
  });

  return out;
}

export function reserveRows(ds: Dataset, onDate: string, base?: string, role?: string, coversReportUtc?: string): Reserve[] {
  const reportMin = coversReportUtc
    ? new Date(coversReportUtc).getUTCHours() * 60 + new Date(coversReportUtc).getUTCMinutes()
    : null;
  return ds.reserves
    .filter((r) => r.dates.includes(onDate))
    .filter((r) => !base || r.base === base)
    .map((r) => {
      const c = ds.crewById.get(r.crew_id)!;
      const s = hhmmToMin(r.oncall_window_utc.start);
      const e = hhmmToMin(r.oncall_window_utc.end);
      return {
        crew_id: r.crew_id, name: c.name, base: r.base, role: c.rank,
        window: r.oncall_window_utc,
        covers: reportMin == null ? null : reportMin >= s && reportMin <= e,
        reachability_minutes: c.reachability_minutes,
      };
    })
    .filter((r) => !role || r.role === role);
}
