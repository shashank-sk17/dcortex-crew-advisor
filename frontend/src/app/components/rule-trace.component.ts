import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';
import { ALL_RULES, RULE_LABELS, RuleCheckEvent } from '../models/agent-events';
import { RuleChipComponent } from './rule-chip.component';

interface Row {
  subject: string;
  checks: Partial<Record<string, RuleCheckEvent>>;
}

/**
 * All seven rules, grouped by the crew/pairing they were run against, with a
 * pass/fail tally. Why: legality is exact arithmetic — the desk needs to see
 * every predicate, not a single legal/illegal verdict.
 */
@Component({
  selector: 'app-rule-trace',
  standalone: true,
  imports: [RuleChipComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './rule-trace.component.html',
  styleUrl: './rule-trace.component.scss',
})
export class RuleTraceComponent {
  readonly allRules = ALL_RULES;
  readonly labels = RULE_LABELS;

  private readonly _checks = signal<RuleCheckEvent[]>([]);

  @Input() set checks(v: RuleCheckEvent[]) {
    this._checks.set(v ?? []);
  }

  readonly rows = computed<Row[]>(() => {
    const bySubject = new Map<string, Row>();
    for (const c of this._checks()) {
      if (c.status === 'NOT_APPLICABLE') continue;
      let row = bySubject.get(c.subject);
      if (!row) {
        row = { subject: c.subject, checks: {} };
        bySubject.set(c.subject, row);
      }
      row.checks[c.rule_id as string] = c;
    }
    return [...bySubject.values()];
  });

  passCount(r: Row): number {
    return Object.values(r.checks).filter((c) => c?.status === 'PASS').length;
  }
  failCount(r: Row): number {
    return Object.values(r.checks).filter((c) => c?.status === 'FAIL').length;
  }
}
