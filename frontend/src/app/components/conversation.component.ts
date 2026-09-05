import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ConversationStore } from '../services/conversation.store';
import { SEEDED_ASKS } from '../services/scenarios.service';
import { AssistantTurn, UserTurn } from '../models/agent-events';
import { AssistantTurnComponent } from './assistant-turn.component';

/**
 * The advisor thread — seeded-prompt empty state, then alternating controller
 * bubbles and streamed assistant turns. Why: it only renders `ConversationStore`
 * state, so all streaming logic stays in the store.
 */
@Component({
  selector: 'app-conversation',
  standalone: true,
  imports: [AssistantTurnComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './conversation.component.html',
  styleUrl: './conversation.component.scss',
})
export class ConversationComponent {
  readonly store = inject(ConversationStore);
  readonly seeds = SEEDED_ASKS;

  asUser(t: unknown): UserTurn {
    return t as UserTurn;
  }
  asAssistant(t: unknown): AssistantTurn {
    return t as AssistantTurn;
  }
}
