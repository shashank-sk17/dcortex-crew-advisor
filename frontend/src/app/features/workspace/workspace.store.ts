import { Injectable, computed, inject, signal } from '@angular/core';
import { API } from '../../core/api.port';
import {
  CandidateResult, CrewLite, Decision, DownstreamLeg, FlightDetail, Option,
  PairingDetail, RuleVerdict,
} from '../../core/api.types';

type Phase = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Drives the disruption-resolution flow: plot the disruption, shrink the funnel,
 * read the 7-rule legality chart for a chosen option, then record the decision.
 * Why: the reasoning IS the screen here, so one store holds the whole chart.
 */
@Injectable()
export class WorkspaceStore {
  private api = inject(API);

  readonly phase = signal<Phase>('idle');
  readonly error = signal<string | null>(null);

  readonly flightId = signal<string | null>(null);
  readonly flight = signal<FlightDetail | null>(null);
  readonly pairing = signal<PairingDetail | null>(null);
  readonly downstream = signal<DownstreamLeg[]>([]);
  readonly candidates = signal<CandidateResult | null>(null);

  readonly selected = signal<Option | null>(null);
  readonly verdicts = signal<RuleVerdict[] | null>(null);
  readonly verdictsFor = signal<string | null>(null);

  readonly decisions = signal<Decision[]>([]);
  readonly recording = signal(false);
  readonly recorded = signal<Decision | null>(null);

  readonly disruptedCrew = computed<CrewLite | null>(() => {
    const c = this.flight()?.crew ?? [];
    return c.find((m) => m.rank === 'Captain') ?? c[0] ?? null;
  });

  readonly options = computed<Option[]>(() => this.candidates()?.options ?? []);
  readonly nearMisses = computed<Option[]>(() => this.candidates()?.near_misses ?? []);

  load(flightId: string): void {
    if (this.flightId() === flightId && this.phase() === 'ready') return;
    this.flightId.set(flightId);
    this.phase.set('loading');
    this.error.set(null);
    this.selected.set(null);
    this.verdicts.set(null);
    this.recorded.set(null);

    this.api.flight(flightId).subscribe({
      next: (f) => {
        if (!f) { this.fail('That flight is not on the roster.'); return; }
        this.flight.set(f);
        const role = this.disruptedCrew()?.role ?? 'Captain';

        this.api.downstream(flightId, 90).subscribe({
          next: (d) => this.downstream.set(d),
          error: () => this.downstream.set([]),
        });

        if (f.pairing_id) {
          this.api.pairing(f.pairing_id).subscribe({
            next: (p) => this.pairing.set(p),
            error: () => this.pairing.set(null),
          });
          this.api.candidates(f.pairing_id, role, f.dep_utc).subscribe({
            next: (c) => { this.candidates.set(c); this.phase.set('ready'); },
            error: () => this.fail('Could not enumerate cover options.'),
          });
        } else {
          this.candidates.set(null);
          this.phase.set('ready');
        }
      },
      error: () => this.fail('Could not load the disruption. Retry.'),
    });

    this.refreshLog();
  }

  retry(): void {
    const id = this.flightId();
    if (id) { this.phase.set('idle'); this.load(id); }
  }

  selectOption(o: Option): void {
    this.selected.set(o);
    this.recorded.set(null);
    const pid = this.flight()?.pairing_id;
    if (o.crew_id && pid) {
      this.verdictsFor.set(o.crew_id);
      if (o.verdicts?.length) { this.verdicts.set(o.verdicts); return; }
      this.verdicts.set(null);
      this.api.crewLegality(o.crew_id, pid).subscribe({
        next: (v) => { if (this.selected() === o) this.verdicts.set(v); },
        error: () => this.verdicts.set([]),
      });
    } else {
      this.verdicts.set([]);
      this.verdictsFor.set(null);
    }
  }

  record(note: string): void {
    const o = this.selected();
    const ref = this.flightId();
    if (!o || !ref || this.recording()) return;
    this.recording.set(true);
    this.api.postDecision({
      disruption_ref: ref,
      chosen_option: o,
      weights: {},
      accepted: true,
      note: note.trim() || undefined,
    }).subscribe({
      next: (d) => {
        this.recording.set(false);
        this.recorded.set(d);
        this.refreshLog();
      },
      error: () => { this.recording.set(false); this.error.set('Could not record the decision. Retry.'); },
    });
  }

  private refreshLog(): void {
    this.api.getDecisions().subscribe({
      next: (d) => this.decisions.set(d),
      error: () => { /* keep last */ },
    });
  }

  private fail(msg: string): void {
    this.error.set(msg);
    this.phase.set('error');
  }
}
