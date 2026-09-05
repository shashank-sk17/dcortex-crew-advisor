import { ChangeDetectionStrategy, Component, Input, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import {
  AssistantTurn, ConsequenceAnswer, LookupAnswer, Option, ReplacementAnswer,
} from '../models/agent-events';
import { API } from '../core/api.port';
import { Decision } from '../core/api.types';
import { ConversationStore } from '../services/conversation.store';
import { Tier1TableComponent } from './tier1-table.component';
import { ImpactCardComponent } from './impact-card.component';
import { OptionsCardComponent } from './options-card.component';
import { RuleTraceComponent } from './rule-trace.component';
import { TracePanelComponent } from './trace-panel.component';
import { AbstainCardComponent } from './abstain-card.component';

const TIER_LABEL: Record<number, string> = {
  1: 'Lookup',
  2: 'Replacement',
  3: 'Consequence',
};

/**
 * One advisor answer, rendered deterministic-first: typed answer card → rule
 * trace → reasoning trail → LLM prose LAST. Why: the layout is the argument —
 * delete the prose and the answer is still complete.
 */
@Component({
  selector: 'app-assistant-turn',
  standalone: true,
  imports: [
    DecimalPipe, Tier1TableComponent, ImpactCardComponent, OptionsCardComponent,
    RuleTraceComponent, TracePanelComponent, AbstainCardComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './assistant-turn.component.html',
  styleUrl: './assistant-turn.component.scss',
})
export class AssistantTurnComponent {
  @Input({ required: true }) turn!: AssistantTurn;

  private api = inject(API);
  private conversation = inject(ConversationStore);

  /** The controller's decision on this turn's recommendation, once recorded. */
  readonly decision = signal<Decision | null>(null);
  readonly showModify = signal(false);
  readonly chosenCrewId = signal<string | null>(null);
  readonly reason = signal('');
  readonly deciding = signal(false);

  get tierLabel(): string | null {
    return this.turn.tier != null ? (TIER_LABEL[this.turn.tier] ?? `Tier ${this.turn.tier}`) : null;
  }

  get lookup(): LookupAnswer | null {
    return this.turn.answer?.kind === 'lookup' ? this.turn.answer : null;
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
    const ref = this.turn.entities['flight_id'] ?? this.turn.entities['pairing_id'] ?? this.turn.id;
    this.api.postDecision({
      disruption_ref: ref, chosen_option: option, weights: {}, accepted, note: reason || undefined,
    }).subscribe({
      next: (d) => {
        this.deciding.set(false);
        this.showModify.set(false);
        this.decision.set(d);
        const msg = reason
          ? `Confirm assignment: ${option.crew_id} — ${option.action} for ${ref}. Reason: ${reason}`
          : `Confirm assignment: ${option.crew_id} — ${option.action} for ${ref}.`;
        this.conversation.ask(msg);
      },
      error: () => {
        this.deciding.set(false);
        this.conversation.pushNote('Could not record that decision — retry.');
      },
    });
  }
}
