import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { RuleCheckEvent, RuleStatus } from '../models/agent-events';
import { IconComponent, IconName } from './icon.component';

/**
 * One rule's verdict — id, pass/fail glyph, margin, and the arithmetic detail.
 * Why: a single reusable row so the legality trace reads like the rulebook.
 */
@Component({
  selector: 'app-rule-chip',
  standalone: true,
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './rule-chip.component.html',
  styleUrl: './rule-chip.component.scss',
})
export class RuleChipComponent {
  @Input({ required: true }) ruleId!: string;
  @Input() label = '';
  @Input() check: RuleCheckEvent | null = null;

  get status(): RuleStatus | 'UNKNOWN' {
    return this.check?.status ?? 'UNKNOWN';
  }
  get statusIcon(): IconName {
    return this.status === 'PASS' ? 'check' : this.status === 'FAIL' ? 'breach' : 'clock';
  }
}
