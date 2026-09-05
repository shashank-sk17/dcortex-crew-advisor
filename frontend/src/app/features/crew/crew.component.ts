import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { API } from '../../core/api.port';
import { AppState } from '../../core/app-state';
import { AdvisorBus } from '../advisor/advisor-bus';
import { CrewDetail, CrewFilter, CrewRow, DutyClock, RuleVerdict } from '../../core/api.types';
import { ModalComponent } from '../../components/modal.component';
import { IconComponent } from '../../components/icon.component';

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
  imports: [IconComponent, DecimalPipe, ModalComponent],
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
  readonly listLoading = signal(false);
  readonly selectedId = signal<string | null>(null);
  readonly detail = signal<CrewDetail | null>(null);
  readonly detailLoading = signal(false);
  readonly detailError = signal<string | null>(null);
  /** Fetched separately from crewDetail(): GET /crew/{id} doesn't return
   * duty_clock on the live backend, but GET /crew/{id}/duty-clock does. */
  readonly dutyClock = signal<DutyClock | null>(null);
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
      this.listLoading.set(true);
      this.api.crew({ date, filter, role, q: query }).subscribe({
        next: (r) => { this.listLoading.set(false); this.rows.set(r); },
        error: () => { this.listLoading.set(false); this.rows.set([]); },
      });
    });
  }

  setFilter(f: CrewFilter): void { this.filter.set(f); }
  setRole(v: string): void { this.role.set(v || null); }
  setQ(v: string): void { this.q.set(v); }

  select(id: string): void {
    this.selectedId.set(id);
    this.detail.set(null);
    this.detailError.set(null);
    this.detailLoading.set(true);
    this.dutyClock.set(null);
    this.verdicts.set(null);
    this.api.crewDetail(id, this.state.date()).subscribe({
      next: (d) => { this.detail.set(d); this.detailLoading.set(false); },
      error: () => {
        this.detailLoading.set(false);
        this.detailError.set('Could not load crew detail — the backend may be unreachable.');
      },
    });
    this.api.dutyClock(id, this.state.date()).subscribe({
      next: (dc) => this.dutyClock.set(dc),
      error: () => {}, // shown as "not available" in the template — not fatal to the drawer
    });
  }
  close(): void {
    this.selectedId.set(null);
    this.detail.set(null);
    this.detailError.set(null);
    void this.router.navigate(['/crew']);
  }
  checkLegality(crewId: string, pairingId: string): void {
    this.checkedPairing.set(pairingId);
    this.api.crewLegality(crewId, pairingId).subscribe((v) => this.verdicts.set(v));
  }
  glyph(s: string): 'check' | 'breach' | 'clock' {
    return s === 'PASS' ? 'check' : s === 'FAIL' ? 'breach' : 'clock';
  }
  ask(d: CrewDetail): void {
    this.bus.ask(`Tell me about ${d.crew_id} (${d.rank}, ${d.base}) — duty headroom, expiring certs, and any risk.`);
    this.close();
  }
}
