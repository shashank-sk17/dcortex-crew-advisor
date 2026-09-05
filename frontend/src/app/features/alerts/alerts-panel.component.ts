import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { Router } from '@angular/router';
import { API } from '../../core/api.port';
import { AppState } from '../../core/app-state';
import { AdvisorBus } from '../advisor/advisor-bus';
import { Alert } from '../../core/api.types';
import { AccordionItemComponent } from '../../components/accordion-item.component';

type Sev = 'critical' | 'warning' | 'info';

/**
 * Right rail — human-in-the-loop queue: the things the controller must decide on
 * for the selected day. Grouped by severity, collapsed to a count by default so
 * critical work isn't buried under a wall of info-level noise — open the group
 * that matters, the rest wait quietly.
 */
@Component({
  selector: 'app-alerts-panel',
  standalone: true,
  imports: [AccordionItemComponent, NgTemplateOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './alerts-panel.component.html',
  styleUrl: './alerts-panel.component.scss',
})
export class AlertsPanelComponent {
  private api = inject(API);
  private state = inject(AppState);
  private bus = inject(AdvisorBus);
  private router = inject(Router);

  readonly alerts = signal<Alert[]>([]);
  readonly openSection = signal<Sev | null>(null);

  constructor() {
    effect(() => {
      const d = this.state.date();
      this.api.alerts(d, 'open').subscribe((raw) => {
        const a = raw.map((x) => (x.title && x.detail ? x : { ...x, ...describe(x) }));
        this.alerts.set(a);
        // default-open the worst non-empty group so the highest-priority work is what greets you
        const first = (['critical', 'warning', 'info'] as Sev[]).find((s) => a.some((x) => x.severity === s));
        this.openSection.set(first ?? null);
      });
    });
  }

  visible(): Alert[] {
    return this.alerts().filter((a) => a.status === 'open');
  }
  bySev(sev: Sev): Alert[] {
    return this.visible().filter((a) => a.severity === sev);
  }
  readonly critical = computed(() => this.bySev('critical'));
  readonly warning = computed(() => this.bySev('warning'));
  readonly info = computed(() => this.bySev('info'));

  toggle(s: Sev): void {
    this.openSection.set(this.openSection() === s ? null : s);
  }

  ask(prompt: string): void {
    this.bus.ask(prompt);
  }
  go(link: string): void {
    void this.router.navigateByUrl(link);
  }
  ack(a: Alert): void {
    this.api.ackAlert(a.id).subscribe(() => this.patch(a.id, 'acknowledged'));
  }
  resolve(a: Alert): void {
    this.api.resolveAlert(a.id).subscribe(() => this.patch(a.id, 'resolved'));
  }
  private patch(id: string, status: Alert['status']): void {
    this.alerts.update((list) => list.map((x) => (x.id === id ? { ...x, status } : x)));
  }
}

/**
 * The live GET /alerts sends a flat, type-specific shape with no
 * title/detail at all (see the `Alert` doc comment in api.types.ts) — this
 * derives the human-readable text the row needs from whichever
 * type-specific fields actually arrived, instead of leaving it blank.
 */
function describe(a: Alert): { title: string; detail: string } {
  if (a.type === 'certification_expiry' || a.cert_type) {
    const label = (a.cert_type ?? 'certification').replace(/_/g, ' ');
    return {
      title: `${a.crew_id ?? a.subject?.id ?? 'Unknown crew'} — ${label} expiring`,
      detail: `Valid to ${a.valid_to ?? '—'}` + (a.days_to_expiry != null ? ` · ${a.days_to_expiry}d left` : ''),
    };
  }
  if (a.type === 'risk_signal' || a.risk_score != null) {
    const pct = a.risk_score != null ? Math.round(a.risk_score * 100) : null;
    return {
      title: `${a.crew_id ?? a.subject?.id ?? 'Unknown crew'} — elevated disruption risk` + (pct != null ? ` (${pct}%)` : ''),
      detail: a.drivers?.length ? a.drivers.join('; ') : 'No driver detail from the backend.',
    };
  }
  return { title: a.title ?? a.type ?? 'Alert', detail: a.detail ?? '' };
}
