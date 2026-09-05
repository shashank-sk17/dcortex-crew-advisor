import { Injectable, inject, signal } from '@angular/core';
import { API } from './api.port';
import { Meta } from './api.types';

/**
 * The working date (and meta for the picker), shared across every view.
 * Why: one signal drives board, crew, alerts and sidebar so they never disagree
 * on which day is being controlled.
 */
@Injectable({ providedIn: 'root' })
export class AppState {
  private api = inject(API);

  readonly date = signal<string>('2026-09-14');
  readonly meta = signal<Meta | null>(null);

  /**
   * The live GET /meta (api/meta_routes.py) returns only
   * `{crew_count, flight_count, pairing_count, reserve_count}` today — no
   * `dates`/`week`/`hub`/`currency`/`snapshot_utc`. `m.dates.includes(...)`
   * unguarded threw on every real-backend page load; guarded here rather
   * than fabricating a date range the backend hasn't sent.
   */
  init(): void {
    this.api.meta().subscribe((m) => {
      this.meta.set(m);
      if (m.dates && m.week && !m.dates.includes(this.date())) this.date.set(m.week.start);
    });
  }

  setDate(d: string): void {
    this.date.set(d);
  }
}
