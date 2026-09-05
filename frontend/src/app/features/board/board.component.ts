import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { API } from '../../core/api.port';
import { AppState } from '../../core/app-state';
import { AdvisorBus } from '../advisor/advisor-bus';
import { CandidateResult, DelayRank, DownstreamLeg, FlightDetail, FlightRow } from '../../core/api.types';
import { ModalComponent } from '../../components/modal.component';
import { IconComponent } from '../../components/icon.component';

/**
 * Main display — the day's flights ranked and colour-coded by disruption risk
 * (`delay_rank`), with a drawer per flight showing operating crew, the downstream
 * tail cascade, and reserve-pool cover options. Why: the board answers "what's
 * fragile right now and what breaks next" before the controller has to ask.
 */
@Component({
  selector: 'app-board',
  standalone: true,
  imports: [IconComponent, DatePipe, DecimalPipe, ModalComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './board.component.html',
  styleUrl: './board.component.scss',
})
export class BoardComponent {
  readonly state = inject(AppState);
  private api = inject(API);
  private bus = inject(AdvisorBus);
  private route = inject(ActivatedRoute);

  readonly ranks: DelayRank[] = ['critical', 'high', 'medium', 'low'];
  readonly rankFilter = signal<DelayRank | null>(null);
  readonly listLoading = signal(false);
  readonly selectedId = signal<string | null>(null);
  readonly detail = signal<FlightDetail | null>(null);
  readonly detailLoading = signal(false);
  readonly detailError = signal<string | null>(null);
  readonly down = signal<DownstreamLeg[]>([]);
  readonly cover = signal<CandidateResult | null>(null);

  private readonly all = signal<FlightRow[]>([]);
  readonly rows = computed(() => {
    const rf = this.rankFilter();
    return rf ? this.all().filter((f) => f.delay_rank === rf) : this.all();
  });

  private qp = toSignal(this.route.queryParamMap);

  constructor() {
    effect(() => {
      const d = this.state.date();
      this.listLoading.set(true);
      this.api.flights({ date: d }).subscribe({
        next: (rows) => {
          this.listLoading.set(false);
          this.all.set(rows);
          const want = this.qp()?.get('flight');
          if (want && rows.some((r) => r.flight_id === want)) {
            const row = rows.find((r) => r.flight_id === want)!;
            this.select(row);
          }
        },
        error: () => { this.listLoading.set(false); this.all.set([]); },
      });
    });
  }

  toggleRank(r: DelayRank): void {
    this.rankFilter.update((c) => (c === r ? null : r));
  }

  select(f: FlightRow): void {
    this.selectedId.set(f.flight_id);
    this.detail.set(null);
    this.detailError.set(null);
    this.detailLoading.set(true);
    this.cover.set(null);
    this.down.set([]);
    this.api.flight(f.flight_id).subscribe({
      next: (d) => { this.detail.set(d); this.detailLoading.set(false); },
      error: () => {
        this.detailLoading.set(false);
        this.detailError.set('Could not load flight detail — the backend may be unreachable.');
      },
    });
    this.api.downstream(f.flight_id, 90).subscribe({ next: (l) => this.down.set(l), error: () => {} });
    if (f.pairing_id) {
      this.api.candidates(f.pairing_id, 'Captain', f.dep_utc).subscribe({
        next: (c) => this.cover.set(c),
        error: () => {},
      });
    }
  }

  close(): void {
    this.selectedId.set(null);
    this.detail.set(null);
    this.detailError.set(null);
  }

  askCover(d: FlightDetail): void {
    this.bus.ask(`${d.crew[0]?.role ?? 'Captain'} on pairing ${d.pairing_id} is unavailable for ${d.flight_no} on ${d.date}. Produce ranked resolution options with costs.`);
    this.close();
  }
}
