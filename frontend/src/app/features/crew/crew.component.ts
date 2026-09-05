import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { API } from '../../core/api.port';
import { AppState } from '../../core/app-state';
import { AdvisorBus } from '../advisor/advisor-bus';
import { CrewDetail, CrewFilter, CrewRow, RuleVerdict } from '../../core/api.types';
import { ModalComponent } from '../../components/modal.component';

const FILTERS: { key: CrewFilter; label: string }[] = [
  { key: 'needs_attention', label: 'Needs attention' },
  { key: 'on_duty', label: 'On duty' },
  { key: 'off_duty', label: 'Off duty' },
  { key: 'on_reserve', label: 'On reserve' },
  { key: 'all', label: 'All' },
];
const ROLES = ['Captain', 'First Officer', 'Senior Cabin Crew', 'Cabin Crew'];

/**
 * Crew roster — filterable list (needs-attention / on-off duty / reserve / role)
 * with a detail drawer: duty clock, expiring certs, risk drivers, and an on-demand
 * 7-rule legality check against any of the crew's pairings. Why: the desk needs
 * "who can I move, and does it break a rule" answerable in two clicks.
 */
@Component({
  selector: 'app-crew',
  standalone: true,
  imports: [DecimalPipe, ModalComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './crew.component.html',
  styleUrl: './crew.component.scss',
})
export class CrewComponent {
  readonly state = inject(AppState);
  private api = inject(API);
  private bus = inject(AdvisorBus);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  readonly filters = FILTERS;
  readonly roles = ROLES;
  readonly filter = signal<CrewFilter>('needs_attention');
  readonly role = signal<string | null>(null);
  readonly q = signal<string>('');
  readonly rows = signal<CrewRow[]>([]);
  readonly selectedId = signal<string | null>(null);
  readonly detail = signal<CrewDetail | null>(null);
  readonly verdicts = signal<RuleVerdict[] | null>(null);
  readonly checkedPairing = signal<string>('');

  private qp = toSignal(this.route.queryParamMap);
  private pm = toSignal(this.route.paramMap);

  constructor() {
    effect(() => {
      const qf = this.qp()?.get('filter') as CrewFilter | null;
      if (qf) this.filter.set(qf);
    });
    effect(() => {
      const id = this.pm()?.get('id');
      if (id) this.select(id);
    });
    effect(() => {
      const date = this.state.date();
      const filter = this.filter();
      const role = this.role() ?? undefined;
      const query = this.q() || undefined;
      this.api.crew({ date, filter, role, q: query }).subscribe((r) => this.rows.set(r));
    });
  }

  setFilter(f: CrewFilter): void { this.filter.set(f); }
  setRole(v: string): void { this.role.set(v || null); }
  setQ(v: string): void { this.q.set(v); }

  select(id: string): void {
    this.selectedId.set(id);
    this.verdicts.set(null);
    this.api.crewDetail(id, this.state.date()).subscribe((d) => this.detail.set(d));
  }
  close(): void {
    this.selectedId.set(null);
    this.detail.set(null);
    void this.router.navigate(['/crew']);
  }
  checkLegality(crewId: string, pairingId: string): void {
    this.checkedPairing.set(pairingId);
    this.api.crewLegality(crewId, pairingId).subscribe((v) => this.verdicts.set(v));
  }
  glyph(s: string): string {
    return s === 'PASS' ? '✓' : s === 'FAIL' ? '✗' : '·';
  }
  ask(d: CrewDetail): void {
    this.bus.ask(`Tell me about ${d.crew_id} (${d.rank}, ${d.base}) — duty headroom, expiring certs, and any risk.`);
    this.close();
  }
}
