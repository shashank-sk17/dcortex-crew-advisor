import { ChangeDetectionStrategy, Component, Input, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import {
  AssistantTurn, ConsequenceAnswer, LookupAnswer, Option, ReplacementAnswer,
} from '../models/agent-events';
import { API } from '../core/api.port';
import { Decision } from '../core/api.types';
import { ConversationStore } from '../services/conversation.store';

/**
 * One advisor answer: the prose, plus Accept/Modify when it recommends someone.
 *
 * This used to render deterministic-first — answer card, rule trace, reasoning
 * trail, prose last. That surfaced every stage of the pipeline in the chat and
 * buried the answer under it. Now the prose IS the answer and the pipeline is
 * not shown.
 *
 * Accept/Modify stayed: without them a ranked recommendation cannot be acted
 * on and no decision reaches the audit log.
 */
@Component({
  selector: 'app-assistant-turn',
  standalone: true,
  imports: [DecimalPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './assistant-turn.component.html',
  styleUrl: './assistant-turn.component.scss',
})
export class AssistantTurnComponent {
  @Input({ required: true }) turn!: AssistantTurn;

  private api = inject(API);
  private conversation = inject(ConversationStore);

  readonly showModify = signal(false);
  readonly chosenCrewId = signal<string | null>(null);
  readonly reason = signal('');
  readonly deciding = signal(false);

  /** The pairing or flight this turn is about, when it names one. */
  get knownRef(): string | null {
    return this.turn.entities['pairing_id'] ?? this.turn.entities['flight_id'] ?? null;
  }

  /**
   * Key for the assignment this turn would record.
   *
   * Falls back to the recommended crew id rather than the turn's UUID, so the
   * agent's "Recorded: …" acknowledgment — a different turn, carrying the same
   * inherited options — resolves to the same key and shows the assignment
   * instead of offering to make it again.
   */
  get disruptionRef(): string {
    const opts = this.replacement?.options ?? this.consequence?.options ?? [];
    return this.knownRef ?? opts[0]?.crew_id ?? this.turn.id;
  }

  /** The assignment recorded against this disruption, by any turn. */
  decision(): Decision | null {
    return this.conversation.decisionFor(this.disruptionRef);
  }

  get replacement(): ReplacementAnswer | null {
    return this.turn.answer?.kind === 'replacement' ? this.turn.answer : null;
  }
  get consequence(): ConsequenceAnswer | null {
    return this.turn.answer?.kind === 'consequence' ? this.turn.answer : null;
  }

  /** Whether this answer carries a recommendation at all — gates showing Accept/Modify.
   * An `awaiting` turn never does: it's a question, not a finding (§2). */
  get hasOptions(): boolean {
    if (this.turn.awaiting) return false;
    return (this.replacement?.options?.length ?? 0) > 0 || (this.consequence?.options?.length ?? 0) > 0;
  }

  /**
   * The "Modify" dropdown's source — deliberately everyone the agent did NOT put
   * an Accept button in front of: near-misses (legal, just not top-ranked) and
   * excluded candidates (blocked by a rule — assignable only as a logged override).
   * The already-suggested `options` list is never repeated here.
   */
  get modifyOptions(): Option[] {
    const nearMiss = this.replacement?.near_misses ?? [];
    const overrides: Option[] = (this.replacement?.excluded ?? []).map((x) => {
      const rules = x.rules ?? x.verdicts?.map((v) => v.rule_id) ?? [];
      const why = x.reason ?? (rules.length ? `fails ${rules.join(', ')}` : 'excluded by the agent');
      return {
        action: `Assign ${x.crew_id} — override (${why})`,
        crew_id: x.crew_id, legal: false, rules_checked: rules,
        cost_inr: 0, delay_hours: 0, rank: 0,
      };
    });
    return [...nearMiss, ...overrides].filter((o) => o.crew_id);
  }

  /**
   * The legal options the prose actually recommends, as Assign buttons. The
   * options card used to carry these; with it gone they would otherwise be
   * unreachable, leaving a recommendation you can read but not act on.
   * Capped at three — the prose names one or two, and a wall of buttons is
   * the card by another name.
   */
  get acceptableOptions(): Option[] {
    const opts = this.replacement?.options ?? this.consequence?.options ?? [];
    return opts.filter((o) => o.crew_id && o.legal).slice(0, 3);
  }

  /** The agent asked a question instead of answering — docs/FRONTEND.md §2. */
  get awaiting(): 'confirmation' | 'detail' | null {
    return this.turn.awaiting;
  }

  /** The controller accepted one of the options-card's own per-row suggestions, as-is. */
  acceptOption(o: Option): void {
    this.record(o, true);
  }

  startModify(): void {
    this.showModify.set(true);
  }
  cancelModify(): void {
    this.showModify.set(false);
    this.chosenCrewId.set(null);
    this.reason.set('');
  }
  confirmModify(): void {
    const picked = this.modifyOptions.find((o) => o.crew_id === this.chosenCrewId());
    if (picked) this.record(picked, false, this.reason().trim());
  }

  /**
   * Accept/Modify don't just write an audit row — they hand the choice to the
   * agent as an instruction, same channel as any question, so the confirmation
   * the controller reads is a real streamed reply, not a string this component
   * invented. The /decisions POST still runs alongside it so the audit trail
   * is real too — in production, the agent's own tool call would do both in
   * one request; here the two mocks are separate, so both are triggered.
   */
  private record(option: Option, accepted: boolean, reason?: string): void {
    this.deciding.set(true);
    const ref = this.disruptionRef;
    this.api.postDecision({
      disruption_ref: ref, chosen_option: option, weights: {}, accepted, note: reason || undefined,
    }).subscribe({
      next: (d) => {
        this.deciding.set(false);
        this.showModify.set(false);
        this.conversation.recordDecision(ref, d);
        // Name the pairing only when we actually know it. The fallback ref is
        // a turn UUID, and "…for adabb2b3-65ee-4f21-8afb-6342b8ef38f8" was
        // being shown to the controller as if it meant something.
        const where = this.knownRef ? ` for ${this.knownRef}` : '';
        const msg = reason
          ? `Confirm assignment: ${option.crew_id} — ${option.action}${where}. Reason: ${reason}`
          : `Confirm assignment: ${option.crew_id} — ${option.action}${where}.`;
        this.conversation.ask(msg);
      },
      error: () => {
        this.deciding.set(false);
        this.conversation.pushNote('Could not record that decision — retry.');
      },
    });
  }
}
