import { ChangeDetectionStrategy, Component, Input, computed, signal } from '@angular/core';
import { RuleVerdict } from '../../core/api.types';

const RULE_LABEL: Record<string, string> = {
  'RULE-FDP-01': 'Flight duty period',
  'RULE-DUTY-02': 'Duty · 7 calendar days',
  'RULE-FLT-03': 'Block · 28 calendar days',
  'RULE-REST-04': 'Rest before report',
  'RULE-QUAL-05': 'Type rating',
  'RULE-CERT-06': 'Certifications',
  'RULE-BASE-07': 'Base / deadhead',
};
const ORDER = ['RULE-FDP-01', 'RULE-DUTY-02', 'RULE-FLT-03', 'RULE-REST-04', 'RULE-QUAL-05', 'RULE-CERT-06', 'RULE-BASE-07'];

interface Row {
  id: string;
  label: string;
  status: RuleVerdict['status'] | 'PENDING';
  detail: string;
  numeric: boolean;
  legalPct: number;   // where the legal boundary sits, 0-100
  markPct: number;    // where the candidate's value sits, 0-100
  used?: number;
  limit?: number;
  headroom?: number;
  unit: string;
}

/**
 * The seven rules drawn as bounded regions with the candidate's position plotted
 * against each — inside the legal zone, or outside it by a measured margin.
 * This is the surface's memorable moment.
 */
@Component({
  selector: 'app-legality-chart',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './legality-chart.component.html',
  styleUrl: './legality-chart.component.scss',
})
export class LegalityChartComponent {
  private readonly _v = signal<RuleVerdict[] | null>(null);
  @Input() subject: string | null = null;
  @Input() set verdicts(v: RuleVerdict[] | null) { this._v.set(v); }

  readonly pending = computed(() => this._v() === null);

  readonly rows = computed<Row[]>(() => {
    const byId = new Map((this._v() ?? []).map((v) => [v.rule_id, v]));
    return ORDER.map((id) => {
      const v = byId.get(id);
      const unit = id === 'RULE-FLT-03' ? 'h block' : id === 'RULE-REST-04' ? 'h rest' : 'h';
      if (!v) {
        return { id, label: RULE_LABEL[id], status: 'PENDING' as const, detail: 'plotting…',
          numeric: false, legalPct: 0, markPct: 0, unit };
      }
      const numeric = v.used != null && v.limit != null;
      let legalPct = 0, markPct = 0;
      if (numeric) {
        const used = v.used!, limit = v.limit!;
        const isRest = id === 'RULE-REST-04';
        // rest: legal region is >= limit, so plot on a 0..(limit*2) scale with the boundary at 50
        const domain = isRest ? Math.max(limit * 2, used * 1.1) : Math.max(limit, used) * 1.12;
        legalPct = Math.min(100, (limit / domain) * 100);
        markPct = Math.min(100, Math.max(0, (used / domain) * 100));
      }
      return {
        id, label: RULE_LABEL[id], status: v.status, detail: v.detail,
        numeric, legalPct, markPct, used: v.used, limit: v.limit, headroom: v.headroom, unit,
      };
    });
  });

  readonly failCount = computed(() => this.rows().filter((r) => r.status === 'FAIL').length);
  readonly passCount = computed(() => this.rows().filter((r) => r.status === 'PASS').length);

  restLegal(r: Row): boolean {
    return r.id === 'RULE-REST-04';
  }
  marginText(r: Row): string {
    if (r.headroom == null) return '';
    const h = r.headroom;
    const mag = Math.abs(h);
    const hh = Math.floor(mag);
    const mm = Math.round((mag - hh) * 60);
    const span = hh > 0 ? `${hh}h${mm ? String(mm).padStart(2, '0') : ''}` : `${mm}m`;
    return h >= 0 ? `${span} inside` : `${span} outside`;
  }
}
