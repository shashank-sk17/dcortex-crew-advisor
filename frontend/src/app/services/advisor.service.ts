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
 * Transport is POST + fetch()-streamed SSE (EventSource can't POST, and we need
 * the `weights` body for the policy sliders). See docs/CONTRACT_RECONCILIATION.md.
 */
@Injectable({ providedIn: 'root' })
export class AdvisorService {
  private mock = inject(MockAdvisorService);

  ask(query: string, opts: AskOptions = {}): Observable<AgentEvent> {
    if (environment.useMock) return this.mock.ask(query);
    return this.stream(`${environment.apiBase}/api/v1/ask`, { query, stream: true, ...toBody(opts) });
  }

  runScenario(scenarioId: string, prompt: string, opts: AskOptions = {}): Observable<AgentEvent> {
    if (environment.useMock) return this.mock.ask(prompt);
    return this.stream(
      `${environment.apiBase}/api/v1/scenarios/${scenarioId}/run`,
      { query: prompt, stream: true, ...toBody(opts) },
    );
  }

  private stream(url: string, body: Record<string, unknown>): Observable<AgentEvent> {
    return new Observable<AgentEvent>((subscriber) => {
      const ctrl = new AbortController();

      (async () => {
        try {
          const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
            body: JSON.stringify(body),
            signal: ctrl.signal,
          });
          if (!res.ok || !res.body) {
            subscriber.next({ type: 'error', message: `Advisor returned ${res.status}` });
            subscriber.complete();
            return;
          }

          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buf = '';

          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += decoder.decode(value, { stream: true });

            // SSE frames are separated by a blank line
            let sep: number;
            while ((sep = buf.indexOf('\n\n')) !== -1) {
              const frame = buf.slice(0, sep);
              buf = buf.slice(sep + 2);
              const ev = parseFrame(frame);
              if (ev) {
                subscriber.next(ev);
                if (ev.type === 'done' || ev.type === 'error') {
                  ctrl.abort();
                  subscriber.complete();
                  return;
                }
              }
            }
          }
          subscriber.complete();
        } catch (e) {
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

function toBody(opts: AskOptions): Record<string, unknown> {
  const b: Record<string, unknown> = {};
  if (opts.weights) b['weights'] = opts.weights;
  if (opts.asOf) b['as_of'] = opts.asOf;
  return b;
}

/** One `data:` line per frame; ignore the `event:` line (type is inside the JSON). */
function parseFrame(frame: string): AgentEvent | null {
  const dataLine = frame
    .split('\n')
    .map((l) => l.trim())
    .find((l) => l.startsWith('data:'));
  if (!dataLine) return null;
  try {
    return JSON.parse(dataLine.slice(5).trim()) as AgentEvent;
  } catch {
    return { type: 'error', message: 'Malformed event from server' };
  }
}
