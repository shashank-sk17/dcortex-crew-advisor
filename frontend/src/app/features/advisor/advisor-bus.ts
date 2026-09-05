import { Injectable, signal } from '@angular/core';

/** Lets any view push a question into the chat bubble (and open it). */
@Injectable({ providedIn: 'root' })
export class AdvisorBus {
  readonly open = signal(false);
  readonly pending = signal<string | null>(null);

  ask(prompt: string): void {
    this.pending.set(prompt);
    this.open.set(true);
  }
  toggle(): void {
    this.open.update((v) => !v);
  }
  consume(): string | null {
    const p = this.pending();
    this.pending.set(null);
    return p;
  }
}
