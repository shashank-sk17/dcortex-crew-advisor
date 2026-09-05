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

  init(): void {
    this.api.meta().subscribe((m) => {
      this.meta.set(m);
      if (!m.dates.includes(this.date())) this.date.set(m.week.start);
    });
  }

  setDate(d: string): void {
    this.date.set(d);
  }
}
