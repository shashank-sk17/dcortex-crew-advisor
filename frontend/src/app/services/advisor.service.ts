import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { AgentEvent } from '../models/agent-events';
import { MockAdvisorService } from './mock-advisor.service';
import { environment } from '../../environments/environment';

export interface AskOptions {
  weights?: Record<string, number>;
  asOf?: string;
}

/**
 * The only place the app talks to the backend.
 *
 * Integration step for the hackathon = flip `environment.useMock` to false.
 *
 * Transport is a single `POST /api/v1/ask` returning one JSON object — see
 * docs/FRONTEND.md §3. It is NOT a stream: the advisor computes everything
 * deterministically before replying, so there is nothing to stream (§7's
 * `GET /stream` exists separately for a live trace, but the doc is explicit
 * that `/ask` is the source of truth). We still emit an `AgentEvent[]` here,
 * translated from the one JSON response, purely so the existing
 * `reduceTurn`/`ConversationStore` pipeline — built for progressive SSE
 * reveal — can render it with no changes on that side.
 */
@Injectable({ providedIn: 'root' })
export class AdvisorService {
  private mock = inject(MockAdvisorService);

  ask(query: string, opts: AskOptions = {}): Observable<AgentEvent> {
    if (environment.useMock) return this.mock.ask(query);
    return this.askJson(`${advisorBase()}/api/v1/ask`, { query, ...toBody(opts) });
  }

  runScenario(_scenarioId: string, prompt: string, opts: AskOptions = {}): Observable<AgentEvent> {
    if (environment.useMock) return this.mock.ask(prompt);
    // There is no dedicated "run a scenario" endpoint on the real advisor —
    // a scenario is just its prompt, asked like anything else.
    return this.ask(prompt, opts);
  }

  private askJson(url: string, body: Record<string, unknown>): Observable<AgentEvent> {
    return new Observable<AgentEvent>((subscriber) => {
      const ctrl = new AbortController();
      const startedAt = performance.now();

      (async () => {
        try {
          const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal: ctrl.signal,
          });
          const json = await res.json().catch(() => null);

          if (!json) {
            subscriber.next({ type: 'error', message: `Advisor returned ${res.status}` });
            subscriber.complete();
            return;
          }
          if (json.error) {
            const e = json.error;
            subscriber.next({
              type: 'error',
              code: typeof e === 'object' ? e.code : undefined,
              message: typeof e === 'object' ? e.message : String(e),
              hint: typeof e === 'object' ? e.hint : undefined,
            });
            subscriber.complete();
            return;
          }

          // devui's reference server wraps the documented contract under
          // `.response` for its own debug view; the real /ask response is flat.
          const r = json.response ?? json;

          if (r.awaiting) {
            subscriber.next({ type: 'awaiting', kind: r.awaiting, narrative: r.narrative ?? '' });
          } else {
            for (const t of r.trace ?? []) {
              const id = crypto.randomUUID();
              subscriber.next({ type: 'tool_call', id, tool: t.tool, args: t.args ?? {} });
              subscriber.next({
                type: 'tool_result', id, tool: t.tool,
                summary: t.error ? `failed — ${t.error}` : 'ok',
                data: t.result ?? null, ms: t.ms ?? 0,
              });
            }
            subscriber.next({
              type: 'answer',
              tier: r.tier, intent: r.intent, entities: r.entities ?? {},
              answer: r.answer, narrative: r.narrative ?? '',
              citations: r.citations ?? [], confidence: r.confidence ?? 'medium',
              unknowns: r.unknowns ?? [],
            });
          }

          subscriber.next({
            type: 'done',
            elapsed_ms: Math.round(performance.now() - startedAt),
            grounded: (r.unknowns ?? []).length === 0,
          });
          subscriber.complete();
        } catch {
          if (!ctrl.signal.aborted) {
            subscriber.next({ type: 'error', message: 'Lost connection to the advisor' });
          }
          subscriber.complete();
        }
      })();

      return () => ctrl.abort();
    });
  }
}

/** The REST view layer and the advisor are different processes in dev (Gayathri's
 * Flask on :5000 has no /ask route yet — issue #32). `advisorBase` lets the two
 * be pointed at different hosts; falls back to `apiBase` once they're unified. */
function advisorBase(): string {
  return (environment as { advisorBase?: string }).advisorBase ?? environment.apiBase;
}

function toBody(opts: AskOptions): Record<string, unknown> {
  const b: Record<string, unknown> = {};
  if (opts.weights) b['weights'] = opts.weights;
  if (opts.asOf) b['as_of'] = opts.asOf;
  return b;
}
