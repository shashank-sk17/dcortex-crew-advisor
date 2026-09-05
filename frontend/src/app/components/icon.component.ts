import { ChangeDetectionStrategy, Component, Input } from '@angular/core';

export type IconName =
  | 'advisor' | 'check' | 'alert' | 'breach' | 'chevron' | 'collapse'
  | 'clock' | 'crew' | 'flight' | 'reset' | 'close' | 'override' | 'arrow';

/**
 * The console's icon set — authored, one 1.75 stroke on one 24 grid, every
 * glyph inheriting `currentColor` so a chip or button colours its own mark.
 *
 * Drawn rather than borrowed: the emoji and unicode arrows these replace
 * (💬 ✓ ⚠ 🔓 ‹ –) render in whatever face the OS ships, at whatever weight it
 * picks — a different typeface per machine, on a desk meant to read as
 * instrumentation. Circles and rects are expressed as paths so every icon is
 * one uniform list to render.
 */
const PATHS: Record<IconName, string[]> = {
  advisor: ['M21 12a8 8 0 0 1-8 8H7l-4 3v-6.5A8 8 0 0 1 11 4h2a8 8 0 0 1 8 8Z'],
  check: ['m4.5 12.5 5 5 10-11'],
  alert: [
    'M10.3 3.9 2.6 17.4a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
    'M12 8.6v4.9', 'M12 17.1v.3',
  ],
  breach: ['M20.5 12a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0', 'm8.5 8.5 7 7', 'm15.5 8.5-7 7'],
  chevron: ['m9.5 5.5 6.5 6.5-6.5 6.5'],
  collapse: ['M5 12h14'],
  clock: ['M20.5 12a8.5 8.5 0 1 1-17 0 8.5 8.5 0 0 1 17 0', 'M12 7.2V12l3.2 2.2'],
  crew: [
    'M12.5 8.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0',
    'M2.8 19.5a6.4 6.4 0 0 1 12.4 0',
    'M16.5 5.6a3.5 3.5 0 0 1 0 6.6',
    'M18.4 14.5a6.4 6.4 0 0 1 2.9 4.4',
  ],
  flight: ['M10.4 3.2a1.6 1.6 0 0 1 3.2 0v5.3l7.4 4.1v2.3l-7.4-2.2v4.4l2.4 1.7v1.8L12 19.5l-4 1.1v-1.8l2.4-1.7v-4.4L3 14.9v-2.3l7.4-4.1Z'],
  reset: ['M20 12a8 8 0 1 1-2.6-5.9', 'M20.2 4.2v4.4h-4.4'],
  close: ['m6.5 6.5 11 11', 'm17.5 6.5-11 11'],
  override: [
    'M6.5 10.5h11a2 2 0 0 1 2 2v5.5a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-5.5a2 2 0 0 1 2-2Z',
    'M8.2 10.5V7.8a3.8 3.8 0 0 1 7.3-1.4',
  ],
  arrow: ['M4 12h15', 'm13.5 6.5 5.5 5.5-5.5 5.5'],
};

@Component({
  selector: 'app-icon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  styles: [`
    :host { display: inline-flex; flex: none; line-height: 0; }
    svg { display: block; width: 1em; height: 1em; }
  `],
  template: `
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75"
         stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
         [style.width.px]="size" [style.height.px]="size">
      @for (d of paths; track d) { <path [attr.d]="d" /> }
    </svg>
  `,
})
export class IconComponent {
  @Input({ required: true }) name!: IconName;
  /** px; omit to track the inherited font size via the 1em rule above. */
  @Input() size?: number;

  get paths(): string[] {
    return PATHS[this.name] ?? [];
  }
}
