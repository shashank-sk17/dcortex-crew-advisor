import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ConversationStore } from '../services/conversation.store';
import { ScenariosService } from '../services/scenarios.service';
import { BlastRadius, ConsequenceAnswer, Option, ReplacementAnswer } from '../models/agent-events';
import { FunnelComponent } from './funnel.component';
import { RuleTraceComponent } from './rule-trace.component';
import { BlastRadiusComponent } from './blast-radius.component';
import { PolicySlidersComponent } from './policy-sliders.component';

/**
 * The audit surface for the last advisor answer — candidate funnel, 7-rule trace,
 * blast radius, and policy-weighted live re-rank. Why: a controller trusts what
 * they can inspect; this shows every drop, verdict and trade-off behind the answer.
 */
@Component({
  selector: 'app-evidence-rail',
  standalone: true,
  imports: [DecimalPipe, FunnelComponent, RuleTraceComponent, BlastRadiusComponent, PolicySlidersComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './evidence-rail.component.html',
  styleUrl: './evidence-rail.component.scss',
})
export class EvidenceRailComponent {
  readonly store = inject(ConversationStore);
  private readonly scenarios = inject(ScenariosService);
  private readonly _ranked = signal<Option[] | null>(null);

  readonly funnel = computed(() => {
    const a = this.store.lastAssistant()?.answer;
    return a?.kind === 'replacement' ? ((a as ReplacementAnswer).funnel ?? []) : [];
  });

  readonly ruleChecks = computed(() => this.store.lastAssistant()?.ruleChecks ?? []);

  readonly blast = computed<BlastRadius | null>(() => {
    const a = this.store.lastAssistant()?.answer;
    return a?.kind === 'consequence' ? (a as ConsequenceAnswer).blast_radius : null;
  });

  readonly baseOptions = computed<Option[]>(() => {
    const a = this.store.lastAssistant()?.answer;
    if (a?.kind === 'consequence') return (a as ConsequenceAnswer).options ?? [];
    if (a?.kind === 'replacement') return (a as ReplacementAnswer).options ?? [];
    return [];
  });

  readonly rankedOptions = computed<Option[]>(() => this._ranked() ?? this.baseOptions());

  async onWeights(patch: Record<string, number>): Promise<void> {
    this.store.setWeights(patch);
    const ranked = await this.scenarios.rank(this.baseOptions(), this.store.weights());
    this._ranked.set(ranked);
  }
}
