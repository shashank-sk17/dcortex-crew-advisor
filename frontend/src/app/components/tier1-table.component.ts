import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { LookupAnswer } from '../models/agent-events';

/**
 * Tier-1 lookup result — a titled table or scalar with its source files listed.
 * Why: even a plain fact shows where it came from, so the answer is auditable.
 *
 * The wire shape varies by backend and the template must not assume either:
 * the real agent (agent/schemas.py) sends `rows: list[dict]` and omits
 * `columns`/`title`/`count`/`citations` entirely, while the mock and the
 * answer-key fixtures send `rows` as arrays of cells with all of those
 * present. Both are normalised to columns + row-arrays here, so the template
 * only ever iterates real arrays — an unguarded loop over a missing field or
 * a plain object throws mid-render, which aborts change detection and freezes
 * the whole turn on whatever it had painted last.
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

  private get rawRows(): unknown[] {
    return Array.isArray(this.data?.rows) ? this.data.rows : [];
  }

  /** Declared columns if the backend sent them, else the union of dict keys. */
  get columns(): string[] {
    if (this.data?.columns?.length) return this.data.columns;
    const keys: string[] = [];
    for (const row of this.rawRows) {
      if (!isRecord(row)) continue;
      for (const k of Object.keys(row)) if (!keys.includes(k)) keys.push(k);
    }
    return keys;
  }

  /** Every row as a flat cell array, ordered to match `columns`. */
  get rows(): (string | number)[][] {
    const cols = this.columns;
    return this.rawRows.map((row) => {
      if (Array.isArray(row)) return row as (string | number)[];
      if (isRecord(row)) return cols.map((c) => format(row[c]));
      return [format(row)];
    });
  }

  get count(): number {
    return this.data?.count ?? this.rawRows.length;
  }

  get citations(): string[] {
    return this.data?.citations ?? [];
  }
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Cells are rendered, not computed on — flatten anything non-scalar rather
 * than printing "[object Object]" at a controller. */
function format(v: unknown): string | number {
  if (v == null) return '—';
  if (typeof v === 'string' || typeof v === 'number') return v;
  if (typeof v === 'boolean') return v ? 'yes' : 'no';
  if (Array.isArray(v)) return v.map((x) => format(x)).join(', ');
  return JSON.stringify(v);
}
