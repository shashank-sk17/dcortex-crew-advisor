import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, Subscription, finalize, scan, tap } from 'rxjs';
import { AdvisorService, AskOptions } from './advisor.service';
import { reduceTurn } from './turn-reducer';
import { AgentEvent, AssistantTurn, Turn, emptyAssistantTurn } from '../models/agent-events';
import { Decision } from '../core/api.types';

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

  /** The turn in flight, held so `stop()` can abort it. */
  private inflight: Subscription | null = null;
  private inflightTurnId: string | null = null;

  /**
   * Assignments recorded this conversation, keyed by what they resolve.
   *
   * This has to live on the conversation, not on a turn. It used to be a
   * signal inside AssistantTurnComponent, so each turn tracked only whether
   * *it* had been clicked — and the agent's "Recorded: …" acknowledgment
   * inherits the previous answer's options, so it rendered a fresh set of
   * Assign buttons for a pairing that had just been crewed. The controller
   * could book the same vacancy twice.
   */
  private readonly _decisions = signal<Record<string, Decision>>({});
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

  /** The assignment already recorded against this disruption, if any. */
  decisionFor(ref: string): Decision | null {
    return this._decisions()[ref] ?? null;
  }

  recordDecision(ref: string, decision: Decision): void {
    this._decisions.update((all) => ({ ...all, [ref]: decision }));
  }

  /**
   * Append a settled, non-streaming assistant turn straight into the thread —
   * used for the agent's reply once a decision (accept / modify) is recorded,
   * so the outcome shows up as a normal message, not just a card mutating in
   * place.
   */
  pushNote(prose: string): void {
    this._turns.update((t) => [
      ...t,
      { ...emptyAssistantTurn(crypto.randomUUID(), null), prose, streaming: false },
    ]);
  }

  ask(question: string): void {
    this.run(question, () => this.advisor.ask(question, this.opts()));
  }

  runScenario(scenarioId: string, prompt: string): void {
    this.run(prompt, () => this.advisor.runScenario(scenarioId, prompt, this.opts()));
  }

  /**
   * Abandon the turn in flight.
   *
   * Unsubscribing runs the teardown in `AdvisorService.askJson`, which aborts
   * the underlying fetch — so this is a real cancellation, not just a UI that
   * looks away. That path deliberately emits no `error` event when the abort
   * was ours, so nothing has to be filtered out here.
   *
   * A tier-3 question can take 25s+ and the composer is disabled for all of
   * it. Without this the controller's only exit is a page reload, which loses
   * the whole thread.
   *
   * Whatever already arrived — the trace so far, any rule checks — stays on
   * screen. It is evidence the agent really did that work, and it is often
   * the reason the controller stopped: they saw enough.
   *
   * The server keeps going. `/ask` is one request that computes to completion,
   * so this frees the controller, not the backend, and the reply is discarded
   * when it lands.
   */
  stop(): void {
    if (!this._busy()) return;
    const id = this.inflightTurnId;
    this.inflight?.unsubscribe();   // finalize() clears busy and settles the turn
    this.inflight = null;
    this.inflightTurnId = null;
    if (!id) return;
    this._turns.update((turns) =>
      turns.map((t) =>
        t.id === id && t.role === 'assistant'
          ? { ...t, streaming: false, status: null, stopped: true }
          : t,
      ),
    );
  }

  /** Clears the local thread and, best-effort, the real advisor's shared
   * server-side conversation — see AdvisorService.reset() for why that
   * matters beyond just tidying the UI. */
  reset(): void {
    this.stop();
    this._turns.set([]);
    this._decisions.set({});
    this.advisor.reset();
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

    this.inflightTurnId = turnId;
    this.inflight = start()
      .pipe(
        scan(reduceTurn, seed),
        tap((turn) => this.replace(turnId, turn)),
        finalize(() => {
          this._busy.set(false);
          this.settle(turnId);
          if (this.inflightTurnId === turnId) {
            this.inflight = null;
            this.inflightTurnId = null;
          }
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
