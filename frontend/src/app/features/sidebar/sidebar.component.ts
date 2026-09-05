import { ChangeDetectionStrategy, Component, effect, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { API } from '../../core/api.port';
import { AppState } from '../../core/app-state';
import { RiskSignal, Summary } from '../../core/api.types';
import { AccordionItemComponent } from '../../components/accordion-item.component';

type Section = 'summary' | 'flights' | 'reserves' | 'watchlist';

/**
 * Left rail — the whole shift at a glance from one `/summary` call plus the
 * disruption watch-list. Collapsed to titles by default, one section open at
 * a time — the controller sees a headline count first, not four panels of
 * detail competing for attention.
 */
@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [DecimalPipe, RouterLink, AccordionItemComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './sidebar.component.html',
  styleUrl: './sidebar.component.scss',
})
export class SidebarComponent {
  private api = inject(API);
  private state = inject(AppState);
  readonly summary = signal<Summary | null>(null);
  readonly risk = signal<RiskSignal[]>([]);
  readonly openSection = signal<Section | null>('summary');

  constructor() {
    effect(() => {
      const d = this.state.date();
      this.api.summary(d).subscribe((s) => this.summary.set(s));
    });
    this.api.riskSignals(0.5).subscribe((r) => this.risk.set(r.slice(0, 8)));
  }

  toggle(s: Section): void {
    this.openSection.set(this.openSection() === s ? null : s);
  }

  poolEntries(s: Summary): [string, number][] {
    return Object.entries(s.reserves.by_base_role)
      .map(([k, v]) => [k.replace('|', ' · '), v] as [string, number])
      .sort((a, b) => a[1] - b[1])
      .slice(0, 6);
  }
}
