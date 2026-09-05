import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { DatePipe, DecimalPipe } from '@angular/common';
import { Decision } from '../../core/api.types';

/**
 * The shift log — timestamped decisions in the margin, each carrying the option,
 * its cost and its rule-check. Why: "done" has a shape, and the next controller
 * reads what was decided and why.
 */
@Component({
  selector: 'app-decision-log',
  standalone: true,
  imports: [DatePipe, DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './decision-log.component.html',
  styleUrl: './decision-log.component.scss',
})
export class DecisionLogComponent {
  @Input() decisions: Decision[] = [];
  @Input() highlight: string | null = null;

  ruleCount(d: Decision): number {
    return d.chosen_option?.rules_checked?.length ?? 0;
  }
}
