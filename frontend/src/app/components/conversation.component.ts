import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { ConversationStore } from '../services/conversation.store';
import { AssistantTurn, UserTurn } from '../models/agent-events';
import { AssistantTurnComponent } from './assistant-turn.component';

/**
 * The advisor thread — alternating controller bubbles and streamed assistant
 * turns. Why: it only renders `ConversationStore` state, so all streaming
 * logic stays in the store.
 *
 * The empty state offers no example questions. A controller opens this with a
 * disruption already in hand; canned prompts would put words in their mouth
 * and make the demo look scripted. Every turn starts with what they typed.
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

  asUser(t: unknown): UserTurn {
    return t as UserTurn;
  }
  asAssistant(t: unknown): AssistantTurn {
    return t as AssistantTurn;
  }
}
