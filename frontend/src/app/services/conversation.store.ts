import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, finalize, scan, tap } from 'rxjs';
import { AdvisorService, AskOptions } from './advisor.service';
import { reduceTurn } from './turn-reducer';
import { AgentEvent, AssistantTurn, Turn, emptyAssistantTurn } from '../models/agent-events';

/**
 * RxJS on the wire, signals in the view.
 *
 * The stream is folded with scan() into an immutable AssistantTurn and pushed
 * into a signal on every event, so the template re-renders the trace, the rule
 * chips and the prose progressively as the agent reasons. That progressive
 * reveal IS the demo — the controller watches the system think.
 */
@Injectable({ providedIn: 'root' })
export class ConversationStore {
  private advisor = inject(AdvisorService);

  private readonly _turns = signal<Turn[]>([]);
  private readonly _busy = signal(false);
  private readonly _weights = signal<Record<string, number>>({
    cost: 1.0, delay: 1.0, pool: 0.5, pairing: 0.8, fairness: 0.3,
  });

  readonly turns = this._turns.asReadonly();
  readonly busy = this._busy.asReadonly();
  readonly weights = this._weights.asReadonly();
  readonly isEmpty = computed(() => this._turns().length === 0);
  readonly lastAssistant = computed<AssistantTurn | null>(() => {
    const t = this._turns();
    for (let i = t.length - 1; i >= 0; i--) {
      if (t[i].role === 'assistant') return t[i] as AssistantTurn;
    }
    return null;
  });

  setWeights(w: Record<string, number>): void {
    this._weights.set({ ...this._weights(), ...w });
  }

  ask(question: string): void {
    this.run(question, () => this.advisor.ask(question, this.opts()));
  }

  runScenario(scenarioId: string, prompt: string): void {
    this.run(prompt, () => this.advisor.runScenario(scenarioId, prompt, this.opts()));
  }

  reset(): void {
    this._turns.set([]);
  }

  private opts(): AskOptions {
    return { weights: this._weights() };
  }

  private run(question: string, start: () => Observable<AgentEvent>): void {
    const text = question.trim();
    if (!text || this._busy()) return;

    const turnId = crypto.randomUUID();
    const seed = emptyAssistantTurn(turnId, text);
    this._busy.set(true);
    this._turns.update((t) => [
      ...t,
      { role: 'user', id: crypto.randomUUID(), text },
      seed,
    ]);

    start()
      .pipe(
        scan(reduceTurn, seed),
        tap((turn) => this.replace(turnId, turn)),
        finalize(() => {
          this._busy.set(false);
          this.settle(turnId);
        }),
      )
      .subscribe({
        error: () =>
          this.replace(turnId, {
            ...seed,
            streaming: false,
            error: 'The advisor stream failed. Retry, or check the backend is running.',
          }),
      });
  }

  private replace(id: string, turn: AssistantTurn): void {
    this._turns.update((turns) => turns.map((t) => (t.id === id ? turn : t)));
  }

  /** Guard against a stream that completes without a `done` event. */
  private settle(id: string): void {
    this._turns.update((turns) =>
      turns.map((t) =>
        t.id === id && t.role === 'assistant' ? { ...t, streaming: false, status: null } : t,
      ),
    );
  }
}
