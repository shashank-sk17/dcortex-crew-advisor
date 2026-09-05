import {
  ChangeDetectionStrategy, Component, EventEmitter, Input, Output,
} from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { Option } from '../../core/api.types';

/**
 * Ranked options as a signed bottom-line ledger: rank, action, and a mono cost
 * column that is the spine. The lead is the advisor's suggestion, not a winner —
 * the controller commits it from the workspace footer.
 */
@Component({
  selector: 'app-options-ledger',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './options-ledger.component.html',
  styleUrl: './options-ledger.component.scss',
})
export class OptionsLedgerComponent {
  @Input() options: Option[] = [];
  @Input() nearMisses: Option[] = [];
  @Input() selected: Option | null = null;
  @Output() pick = new EventEmitter<Option>();

  isSel(o: Option): boolean {
    return this.selected === o
      || (!!this.selected && this.selected.action === o.action && this.selected.crew_id === o.crew_id);
  }
  breakdown(o: Option): [string, number][] {
    return Object.entries(o.cost_breakdown ?? {}).filter(([, v]) => v > 0);
  }
}
