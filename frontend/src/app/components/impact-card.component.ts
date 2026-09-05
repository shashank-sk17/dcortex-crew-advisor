import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { ReplacementAnswer } from '../models/agent-events';

/**
 * Headline impact of a disruption — flights uncrewed now, flights at risk on
 * day 2, passengers affected. Why: the "so what" before the options, so the
 * controller sees scale first.
 */
@Component({
  selector: 'app-impact-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './impact-card.component.html',
  styleUrl: './impact-card.component.scss',
})
export class ImpactCardComponent {
  @Input({ required: true }) data!: ReplacementAnswer;
  short(fid: string): string {
    return fid.split('-2026-')[0];
  }
}
