import { ChangeDetectionStrategy, Component, effect, inject } from '@angular/core';
import { AdvisorBus } from './advisor-bus';
import { ConversationStore } from '../../services/conversation.store';
import { ConversationComponent } from '../../components/conversation.component';
import { ChatComposerComponent } from '../../components/chat-composer.component';
import { EvidenceRailComponent } from '../../components/evidence-rail.component';

/**
 * Floating advisor — a bubble that expands into the streamed reasoning + answer
 * cards (Tier 1/2/3 + abstain) + evidence rail. Why: the conversational layer is
 * a side-channel, not the main UI, and any view can push a question into it.
 */
@Component({
  selector: 'app-chat-bubble',
  standalone: true,
  imports: [ConversationComponent, ChatComposerComponent, EvidenceRailComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './chat-bubble.component.html',
  styleUrl: './chat-bubble.component.scss',
})
export class ChatBubbleComponent {
  readonly bus = inject(AdvisorBus);
  readonly store = inject(ConversationStore);

  constructor() {
    effect(() => {
      if (this.bus.open() && this.bus.pending()) {
        const q = this.bus.consume();
        if (q) this.store.ask(q);
      }
    });

    // pin the newest response's own top to the top of the panel — read it from
    // the start as it streams in, rather than snapping to the bottom of the thread
    effect(() => {
      const last = this.store.lastAssistant();
      if (!last) return;
      queueMicrotask(() => {
        document.getElementById(`turn-${last.id}`)?.scrollIntoView({ block: 'start' });
      });
    });
  }
}
