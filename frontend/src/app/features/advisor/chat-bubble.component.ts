import { ChangeDetectionStrategy, Component, effect, inject } from '@angular/core';
import { AdvisorBus } from './advisor-bus';
import { ConversationStore } from '../../services/conversation.store';
import { ConversationComponent } from '../../components/conversation.component';
import { ChatComposerComponent } from '../../components/chat-composer.component';

/**
 * Floating advisor — a bubble that expands into a plain chat thread. The
 * evidence rail that used to sit alongside it was removed with the rest of the
 * pipeline surface; this reads as a chatbot now.
 */
@Component({
  selector: 'app-chat-bubble',
  standalone: true,
  imports: [ConversationComponent, ChatComposerComponent],
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
