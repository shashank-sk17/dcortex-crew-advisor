import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { Subject, debounceTime } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

const KNOBS: { key: string; label: string; hint: string }[] = [
  { key: 'cost', label: 'Cost', hint: 'weight ₹ per option' },
  { key: 'delay', label: 'Delay', hint: 'weight departure slip' },
  { key: 'pool', label: 'Reserve pool', hint: 'prefer keeping reserves' },
  { key: 'pairing', label: 'Pairing integrity', hint: 'penalise knock-on' },
  { key: 'fairness', label: 'Crew fairness', hint: 'spread callouts' },
];

/**
 * Objective-weight knobs that re-rank the current options client-side (debounced),
 * emitting the changed weights. Why: the human keeps the wheel — trade-offs are
 * tuned live and transparently, with no model call.
 */
@Component({
  selector: 'app-policy-sliders',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './policy-sliders.component.html',
  styleUrl: './policy-sliders.component.scss',
})
export class PolicySlidersComponent {
  readonly knobs = KNOBS;
  @Input() weights: Record<string, number> = {};
  @Output() changed = new EventEmitter<Record<string, number>>();

  private pending: Record<string, number> = {};
  private tick = new Subject<void>();

  constructor() {
    this.tick.pipe(debounceTime(180), takeUntilDestroyed()).subscribe(() => {
      this.changed.emit({ ...this.pending });
      this.pending = {};
    });
  }

  onInput(key: string, value: string): void {
    this.pending[key] = parseFloat(value);
    this.weights = { ...this.weights, [key]: parseFloat(value) };
    this.tick.next();
  }
}
