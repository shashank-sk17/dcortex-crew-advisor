import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { AbstainEvent } from '../models/agent-events';

/**
 * "I can't answer that reliably" card — the reason plus what data would be needed.
 * Why: the brief scores an honest refusal over a confident wrong answer, so it
 * gets its own first-class surface.
 */
@Component({
  selector: 'app-abstain-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './abstain-card.component.html',
  styleUrl: './abstain-card.component.scss',
})
export class AbstainCardComponent {
  @Input({ required: true }) data!: AbstainEvent;
}
