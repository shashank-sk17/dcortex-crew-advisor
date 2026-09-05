import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ConversationStore } from '../services/conversation.store';

/**
 * The advisor input box — Enter to send, Shift+Enter for a newline, Clear to reset.
 * Why: keeps all send/submit wiring in one leaf so the conversation view stays dumb.
 */
@Component({
  selector: 'app-chat-composer',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './chat-composer.component.html',
  styleUrl: './chat-composer.component.scss',
})
export class ChatComposerComponent {
  readonly store = inject(ConversationStore);
  private readonly _text = signal('');

  get text(): string {
    return this._text();
  }
  set text(v: string) {
    this._text.set(v);
  }

  onEnter(ev: Event): void {
    const e = ev as KeyboardEvent;
    if (!e.shiftKey) {
      e.preventDefault();
      this.submit();
    }
  }
  send(ev: Event): void {
    ev.preventDefault();
    this.submit();
  }
  private submit(): void {
    const t = this._text().trim();
    if (!t || this.store.busy()) return;
    this.store.ask(t);
    this._text.set('');
  }
}
