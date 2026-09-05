import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { BlastRadius } from '../models/agent-events';

/**
 * Consequence map for a disruption — headline counts plus the causal edges
 * (direct hit, orphaned day-2 leg, aircraft rotation). Why: shows the four
 * flights that break next, which leg-level thinking misses.
 */
@Component({
  selector: 'app-blast-radius',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './blast-radius.component.html',
  styleUrl: './blast-radius.component.scss',
})
export class BlastRadiusComponent {
  @Input() blast: BlastRadius | null = null;

  label(kind: string): string {
    return (
      { direct: 'direct', orphaned_day2: 'orphaned day 2', aircraft_rotation: 'aircraft', pool: 'pool depletion' } as Record<string, string>
    )[kind] ?? kind;
  }
}
