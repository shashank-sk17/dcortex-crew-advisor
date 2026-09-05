import { reduceTurn } from './turn-reducer';
import { AgentEvent, emptyAssistantTurn } from '../models/agent-events';

describe('reduceTurn', () => {
  const fold = (events: AgentEvent[]) =>
    events.reduce(reduceTurn, emptyAssistantTurn('t'));

  it('appends a pending trace step on tool_call and settles it on tool_result', () => {
    const t = fold([
      { type: 'tool_call', id: 'a', tool: 'find_options', args: { pairing_id: 'P-2291' } },
      { type: 'tool_result', id: 'a', tool: 'find_options', summary: '6 legal', data: {}, ms: 41 },
    ]);
    expect(t.trace.length).toBe(1);
    expect(t.trace[0].pending).toBe(false);
    expect(t.trace[0].summary).toBe('6 legal');
  });

  it('accumulates rule checks and prose', () => {
    const t = fold([
      { type: 'rule_check', rule_id: 'RULE-DUTY-02', subject: 'C-2087', status: 'FAIL', detail: 'over by 1h20m' },
      { type: 'token', text: 'C-3310 ' },
      { type: 'token', text: 'is clean.' },
    ]);
    expect(t.ruleChecks.length).toBe(1);
    expect(t.prose).toBe('C-3310 is clean.');
  });

  it('captures the typed answer object and grounding verdict', () => {
    const t = fold([
      {
        type: 'answer', tier: 2, intent: 'FIND_REPLACEMENT', entities: { crew_id: 'C-1042' },
        answer: { kind: 'replacement', uncovered_flights: [], at_risk_flights: [], passengers_affected: 0, funnel: [], options: [], near_misses: [], excluded: [] },
        narrative: 'n', citations: [], confidence: 'high', unknowns: [],
      },
      { type: 'done', elapsed_ms: 1900, grounded: true },
    ]);
    expect(t.tier).toBe(2);
    expect(t.grounded).toBe(true);
    expect(t.streaming).toBe(false);
  });

  it('records an abstain', () => {
    const t = fold([{ type: 'abstain', reason: 'no data', needed: ['weather feed'] }]);
    expect(t.abstain?.needed).toEqual(['weather feed']);
  });
});
