import {
  ChangeDetectionStrategy, Component, ElementRef, EventEmitter, HostListener, Input, Output, ViewChild,
} from '@angular/core';

/**
 * A glassy popup on dCortex's own scrim + translucency recipe — frosted panel
 * over a blurred, dimmed backdrop. Why: focuses the visitor on one record
 * (a crew member, a flight) without navigating away or losing the board state
 * underneath; closes on backdrop click or Esc, never traps focus silently.
 */
@Component({
  selector: 'app-modal',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './modal.component.html',
  styleUrl: './modal.component.scss',
})
export class ModalComponent {
  @Input() label = 'Details';
  @Output() closed = new EventEmitter<void>();
  @ViewChild('panel') panel?: ElementRef<HTMLElement>;

  @HostListener('document:keydown.escape')
  onEsc(): void {
    this.close();
  }

  onScrimClick(ev: MouseEvent): void {
    if (ev.target === ev.currentTarget) this.close();
  }

  close(): void {
    this.closed.emit();
  }
}
