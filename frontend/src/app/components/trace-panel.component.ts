import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { JsonPipe } from '@angular/common';
import { TraceStep } from '../models/agent-events';

/**
 * Expandable list of the agent's tool calls with args and raw results, streamed
 * live. Why: it's the reasoning trail the brief mandates — always visible, never
 * a debug toggle, so the controller can challenge any step.
 */
@Component({
  selector: 'app-trace-panel',
  standalone: true,
  imports: [JsonPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './trace-panel.component.html',
  styleUrl: './trace-panel.component.scss',
})
export class TracePanelComponent {
  @Input() steps: TraceStep[] = [];
}
