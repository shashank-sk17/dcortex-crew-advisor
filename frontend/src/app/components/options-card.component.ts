import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ExcludedCandidate, Option } from '../models/agent-events';

/**
 * Ranked resolution options with cost breakdown, plus near-misses (one lever from
 * legal) and an expandable list of excluded candidates with their failing rule.
 * Each legal option carries its own Accept button — the controller picks straight
 * off the recommendation, or ignores all of them and modifies instead.
 * Why: the recommendation and the rejected alternatives are shown together, so
 * the controller can see what was considered and why it lost.
 */
@Component({
  selector: 'app-options-card',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './options-card.component.html',
  styleUrl: './options-card.component.scss',
})
export class OptionsCardComponent {
  @Input() options: Option[] = [];
  @Input() nearMisses: Option[] = [];
  @Input() excluded: ExcludedCandidate[] = [];
  /** Set once the controller has accepted one option — marks it, disables the rest. */
  @Input() decidedCrewId: string | null = null;
  @Input() deciding = false;
  @Output() accept = new EventEmitter<Option>();

  entries(o: Record<string, number>): [string, number][] {
    return Object.entries(o);
  }
}
