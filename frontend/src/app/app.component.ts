import { Component } from '@angular/core';
import { CockpitComponent } from './shell/cockpit.component';

/**
 * Bootstrap host — nothing but the cockpit shell.
 * Why: keeps `main.ts`/root free of layout so the shell owns all structure.
 */
@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CockpitComponent],
  template: `<app-cockpit />`,
})
export class AppComponent {}
