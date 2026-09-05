import {
  ChangeDetectionStrategy, Component, EventEmitter, Input, Output,
} from '@angular/core';

/**
 * One collapsible section — a big title, collapsed by default, expands on
 * click. Parent owns which section is open (one at a time), so panels stop
 * showing everything at once and the visitor sees one thing to focus on.
 */
@Component({
  selector: 'app-accordion-item',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './accordion-item.component.html',
  styleUrl: './accordion-item.component.scss',
})
export class AccordionItemComponent {
  @Input() title = '';
  @Input() badge: string | number | null = null;
  @Input() open = false;
  @Output() toggle = new EventEmitter<void>();
}
