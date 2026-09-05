import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { FunnelStage } from '../models/agent-events';

/**
 * The candidate shortlist as a shrinking bar chart (150 → role → qualified →
 * available → legal) with the reason for every drop. Why: it makes the
 * selection defensible — the controller sees who was ruled out and why.
 */
@Component({
  selector: 'app-funnel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './funnel.component.html',
  styleUrl: './funnel.component.scss',
})
export class FunnelComponent {
  @Input() stages: FunnelStage[] = [];

  private max(): number {
    return Math.max(1, ...(this.stages ?? []).map((s) => s.count));
  }
  pct(n: number): number {
    return (n / this.max()) * 100;
  }
  pretty(stage: string): string {
    return stage.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  }
}
