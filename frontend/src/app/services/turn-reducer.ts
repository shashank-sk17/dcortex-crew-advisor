import { AgentEvent, AssistantTurn, TraceStep } from '../models/agent-events';

/**
 * Pure reducer. One AgentEvent folded into one AssistantTurn.
 * Kept pure so it can be unit-tested without a stream and reused by scan().
 */
export function reduceTurn(turn: AssistantTurn, ev: AgentEvent): AssistantTurn {
  switch (ev.type) {
    case 'status':
      return { ...turn, status: ev.text };

    case 'tool_call': {
      const step: TraceStep = { id: ev.id, tool: ev.tool, args: ev.args, pending: true };
      return { ...turn, status: `Calling ${ev.tool}…`, trace: [...turn.trace, step] };
    }

    case 'tool_result':
      return {
        ...turn,
        trace: turn.trace.map((s) =>
          s.id === ev.id
            ? { ...s, summary: ev.summary, data: ev.data, ms: ev.ms, pending: false }
            : s,
        ),
      };

    case 'rule_check':
      return { ...turn, ruleChecks: [...turn.ruleChecks, ev] };

    case 'token':
      return { ...turn, status: null, prose: turn.prose + ev.text };

    case 'answer':
      // Clear the waiting text here, not only on `done` — an answer that has
      // arrived must never still read as "still working", whatever happens to
      // the terminal event.
      return {
        ...turn,
        status: null,
        tier: ev.tier,
        intent: ev.intent,
        entities: ev.entities ?? {},
        answer: ev.answer,
        narrative: ev.narrative ?? '',
        citations: ev.citations ?? [],
        confidence: ev.confidence ?? null,
        unknowns: ev.unknowns ?? [],
      };

    case 'abstain':
      return { ...turn, abstain: ev, status: null };

    case 'awaiting':
      return { ...turn, awaiting: ev.kind, narrative: ev.narrative, status: null };

    case 'done':
      return {
        ...turn,
        streaming: false,
        status: null,
        elapsedMs: ev.elapsed_ms,
        grounded: ev.grounded,
      };

    case 'error':
      return { ...turn, streaming: false, status: null, error: ev.message };

    default:
      return turn;
  }
}
