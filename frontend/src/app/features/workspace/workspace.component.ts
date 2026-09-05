import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { AppState } from '../../core/app-state';
import { WorkspaceStore } from './workspace.store';
import { RouteChartComponent } from './route-chart.component';
import { FunnelStripComponent } from './funnel-strip.component';
import { LegalityChartComponent } from './legality-chart.component';
import { OptionsLedgerComponent } from './options-ledger.component';
import { DecisionLogComponent } from './decision-log.component';

const RULES: [string, string][] = [
  ['RULE-FDP-01', 'Max flight duty period, −0.5h per sector past the 2nd'],
  ['RULE-DUTY-02', 'Max 60 duty h / 7 calendar days'],
  ['RULE-FLT-03', 'Max 100 block h / 28 calendar days'],
  ['RULE-REST-04', 'Min 12h rest before report'],
  ['RULE-QUAL-05', 'Valid type rating for the aircraft'],
  ['RULE-CERT-06', 'All certifications valid on every duty date'],
  ['RULE-BASE-07', 'Reserve callout own-base, else deadhead'],
];

/**
 * The disruption-resolution workspace — the reasoning IS the screen.
 * Left, the rulebook + shift log. Centre, the disruption on a route chart and
 * the 7-rule legality chart. Right, the options ledger with the commit at its foot.
 */
@Component({
  selector: 'app-workspace',
  standalone: true,
  imports: [
    DatePipe, RouterLink,
    RouteChartComponent, FunnelStripComponent, LegalityChartComponent,
    OptionsLedgerComponent, DecisionLogComponent,
  ],
  providers: [WorkspaceStore],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './workspace.component.html',
  styleUrl: './workspace.component.scss',
})
export class WorkspaceComponent {
  readonly store = inject(WorkspaceStore);
  readonly state = inject(AppState);
  private route = inject(ActivatedRoute);
  readonly rules = RULES;

  readonly note = signal('');
  readonly applied = signal(false);
  private pm = toSignal(this.route.paramMap);

  readonly selectedFail = computed(() => (this.store.verdicts() ?? []).some((v) => v.status === 'FAIL'));

  constructor() {
    effect(() => {
      const id = this.pm()?.get('flightId');
      if (id) {
        this.store.load(id);
        this.applied.set(false);
        queueMicrotask(() => this.applied.set(true));
      }
    });
  }

  setNote(v: string): void { this.note.set(v); }

  commit(): void {
    this.store.record(this.note());
    this.note.set('');
  }
}
