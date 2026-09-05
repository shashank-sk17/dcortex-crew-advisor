import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { LookupAnswer } from '../models/agent-events';

/**
 * Tier-1 lookup result — a titled table or scalar with its source files listed.
 * Why: even a plain fact shows where it came from, so the answer is auditable.
 */
@Component({
  selector: 'app-tier1-table',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './tier1-table.component.html',
  styleUrl: './tier1-table.component.scss',
})
export class Tier1TableComponent {
  @Input({ required: true }) data!: LookupAnswer;
}
