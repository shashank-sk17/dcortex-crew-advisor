import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import {
  AssistantTurn, ConsequenceAnswer, LookupAnswer, ReplacementAnswer,
} from '../models/agent-events';
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
    Tier1TableComponent, ImpactCardComponent, OptionsCardComponent,
    RuleTraceComponent, TracePanelComponent, AbstainCardComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './assistant-turn.component.html',
  styleUrl: './assistant-turn.component.scss',
})
export class AssistantTurnComponent {
  @Input({ required: true }) turn!: AssistantTurn;

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
}
