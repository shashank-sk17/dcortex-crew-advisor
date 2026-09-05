import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';
import { FunnelStage } from '../../core/api.types';

/**
 * The candidate search as a descending set of ruled bands — 150 down to the
 * legal few, each drop annotated with its count and reason.
 * Why: it makes the shortlist defensible before the controller asks "why not them".
 */
@Component({
  selector: 'app-funnel-strip',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './funnel-strip.component.html',
  styleUrl: './funnel-strip.component.scss',
})
export class FunnelStripComponent {
  private readonly _s = signal<FunnelStage[]>([]);
  @Input() set stages(v: FunnelStage[]) { this._s.set(v ?? []); }

  readonly rows = computed(() => {
    const s = this._s();
    const max = Math.max(1, ...s.map((x) => x.count));
    return s.map((x) => ({ ...x, pct: (x.count / max) * 100 }));
  });
  readonly legal = computed(() => this.rows().at(-1)?.count ?? 0);
  readonly start = computed(() => this.rows()[0]?.count ?? 0);

  pretty(stage: string): string {
    return stage.replace(/_/g, ' ');
  }
}
