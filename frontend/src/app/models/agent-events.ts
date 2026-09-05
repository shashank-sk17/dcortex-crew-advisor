/**
 * RECONCILED API CONTRACT — see docs/CONTRACT_RECONCILIATION.md.
 *
 * Transport:  POST /api/v1/ask  { query, as_of?, weights?, stream: true }
 *             -> text/event-stream, one JSON AgentEvent per `data:` line.
 *
 * Design rule this encodes:
 *   The LLM produces `token` (prose) and `tool_call` (which tool, with args) — nothing
 *   a controller acts on. Every fact a controller acts on arrives as `tool_result`,
 *   `rule_check`, `answer` or `abstain`, all produced by deterministic Python.
 *   The UI renders those as the primary surface and the prose as commentary.
 */

export type Tier = 0 | 1 | 2 | 3;
export type Confidence = 'high' | 'medium' | 'low';

export type RuleId =
  | 'RULE-FDP-01'
  | 'RULE-DUTY-02'
  | 'RULE-FLT-03'
  | 'RULE-REST-04'
  | 'RULE-QUAL-05'
  | 'RULE-CERT-06'
  | 'RULE-BASE-07';

export const RULE_LABELS: Record<RuleId, string> = {
  'RULE-FDP-01': 'Flight duty period ≤ 13h (−0.5h / sector > 2)',
  'RULE-DUTY-02': 'Duty ≤ 60h / 7 calendar days',
  'RULE-FLT-03': 'Block ≤ 100h / 28 calendar days',
  'RULE-REST-04': 'Rest ≥ 12h before report',
  'RULE-QUAL-05': 'Valid rating for aircraft type',
  'RULE-CERT-06': 'Certifications valid on duty date',
  'RULE-BASE-07': 'Reserve callout from own base (else deadhead)',
};

export const ALL_RULES: RuleId[] = [
  'RULE-FDP-01', 'RULE-DUTY-02', 'RULE-FLT-03', 'RULE-REST-04',
  'RULE-QUAL-05', 'RULE-CERT-06', 'RULE-BASE-07',
];

/* ----------------------------------------------------------------- SSE events */

export interface StatusEvent {
  type: 'status';
  text: string;
}

/** The LLM chose a tool. Args are structured — this is the LLM's only decision. */
export interface ToolCallEvent {
  type: 'tool_call';
  id: string;
  tool: string;
  args: Record<string, unknown>;
}

/** Deterministic code answered. `data` is ground truth; nothing else is. */
export interface ToolResultEvent {
  type: 'tool_result';
  id: string;
  tool: string;
  summary: string;
  data: unknown;
  ms: number;
}

export type RuleStatus = 'PASS' | 'FAIL' | 'NOT_APPLICABLE';

/** One of the seven rules, evaluated by arithmetic. Never by the model. */
export interface RuleCheckEvent {
  type: 'rule_check';
  rule_id: RuleId | string;
  subject: string;            // crew_id / pairing_id the rule was applied to
  status: RuleStatus;
  detail: string;
  margin?: string;            // "1h20m over" / "4h10m spare"
  used?: number;
  limit?: number;
  headroom?: number;
  date?: string;
}

/** Narration chunk from the LLM. Cosmetic. Never load-bearing. */
export interface TokenEvent {
  type: 'token';
  text: string;
}

export interface AnswerEvent {
  type: 'answer';
  tier: Tier;
  intent: string;
  entities: Record<string, string>;
  answer: LookupAnswer | ReplacementAnswer | ConsequenceAnswer;
  narrative: string;
  citations: Citation[];
  confidence: Confidence;
  unknowns: string[];
}

/** The scoring-critical event — "I can't answer that reliably" gets its own card. */
export interface AbstainEvent {
  type: 'abstain';
  reason: string;
  needed?: string[];
}

/**
 * The agent asked the controller something instead of answering — docs/FRONTEND.md §2,
 * "the one thing that will catch you out". There is no recommendation to render yet;
 * the next message the controller sends is the reply, in the same thread.
 */
export interface AwaitingEvent {
  type: 'awaiting';
  kind: 'confirmation' | 'detail';
  narrative: string;
}

export interface DoneEvent {
  type: 'done';
  elapsed_ms: number;
  /** Verifier verdict: every number in the prose traced back to a tool_result. */
  grounded: boolean;
}

export interface ErrorEvent {
  type: 'error';
  code?: string;
  message: string;
  hint?: string;
}

export type AgentEvent =
  | StatusEvent
  | ToolCallEvent
  | ToolResultEvent
  | RuleCheckEvent
  | TokenEvent
  | AnswerEvent
  | AbstainEvent
  | AwaitingEvent
  | DoneEvent
  | ErrorEvent;

/* ------------------------------------------------------------- answer payloads */

export interface Citation {
  kind: 'rule' | 'record';
  id: string;
  source?: string;
}

/**
 * A tier-1 lookup. The real agent (agent/schemas.py) sends only
 * `{kind, rows}` with `rows: list[dict]`; the mock and answer-key fixtures
 * send arrays-of-cells plus title/columns/count/citations. Everything except
 * `kind`/`rows` is optional, and `rows` accepts both shapes —
 * Tier1TableComponent normalises them before the template touches either.
 */
export interface LookupAnswer {
  kind: 'lookup';
  title?: string;
  columns?: string[];
  rows: (string | number)[][] | Record<string, unknown>[];
  scalar?: string;
  count?: number;
  citations?: string[];
}

export interface RuleVerdict {
  rule_id: RuleId | string;
  status: RuleStatus;
  detail: string;
  used?: number;
  limit?: number;
  headroom?: number;
  date?: string;
}

/** Matches the answer-key shape exactly. Do not rename action/crew_id/legal/… */
export interface Option {
  action: string;
  crew_id: string | null;
  legal: boolean;
  rules_checked: (RuleId | string)[];
  cost_inr: number;
  delay_hours: number;
  rank: number;
  // additive — never replacing the above
  cost_breakdown?: Record<string, number>;
  blast_radius?: number;
  coverage?: string;
  reachability_minutes?: number;
  reasoning?: string;
  verdicts?: RuleVerdict[];
  unlock?: string | null;
  _score?: number;
}

export interface FunnelStage {
  stage: string;
  count: number;
  dropped?: number;
  reason?: string;
}

/** Real shape confirmed against agent/tools.py's find_options — `reason` is the
 * prose the doc's excluded[].reason documents; `rules` is the short id list.
 * `verdicts` rides along additively when the failure traces to a specific rule. */
export interface ExcludedCandidate {
  crew_id: string;
  reason?: string;
  rules?: (RuleId | string)[];
  verdicts?: RuleVerdict[];
}

export interface ReplacementAnswer {
  kind: 'replacement';
  /** The agent's pick, when it has one — docs/FRONTEND.md §5 step 2: lead with this. */
  recommended?: Option | null;
  uncovered_flights?: string[];
  at_risk_flights?: string[];
  passengers_affected?: number;
  funnel?: FunnelStage[];
  options?: Option[];
  near_misses?: Option[];
  excluded?: ExcludedCandidate[];
  cancellation_multiple?: number;
  next_tier_cost_inr?: number;
  next_tier_premium_inr?: number;
  /** >0 means the pick is not unique — several plans cost the same. */
  equal_cost_alternatives?: number;
  // A direct legality question ("is C-2087 legal for X") answers here instead
  // of with candidates — subject/legal/verdicts populated, options empty.
  subject?: string | null;
  legal?: boolean | null;
  verdicts?: RuleVerdict[];
}

export interface BlastEdge {
  from: string;
  to: string;
  kind: 'direct' | 'orphaned_day2' | 'aircraft_rotation' | 'pool' | string;
}

export interface BlastRadius {
  nodes: number;
  flights: number;
  aircraft: number;
  passengers: number;
  edges?: BlastEdge[];
}

export interface ConsequenceAnswer {
  kind: 'consequence';
  options?: Option[];
  blast_radius: BlastRadius;
  world_diff?: Record<string, unknown>;
  joint_plan?: { total_cost_inr: number; assignments?: Record<string, unknown> };
  expected_choice?: { crew_id: string | null; rank: number };
}

/* --------------------------------------------------------------- view model */

export interface TraceStep {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  summary?: string;
  data?: unknown;
  ms?: number;
  pending: boolean;
}

export interface AssistantTurn {
  role: 'assistant';
  id: string;
  /** The controller's question this turn answers — echoed compactly instead of the raw payload. */
  query: string | null;
  status: string | null;
  prose: string;
  trace: TraceStep[];
  ruleChecks: RuleCheckEvent[];
  tier: Tier | null;
  intent: string | null;
  entities: Record<string, string>;
  answer: LookupAnswer | ReplacementAnswer | ConsequenceAnswer | null;
  narrative: string;
  citations: Citation[];
  confidence: Confidence | null;
  unknowns: string[];
  abstain: AbstainEvent | null;
  /** Set when the agent asked a question instead of answering — render the
   * prompt, nothing else, and route the next message as the reply (§2). */
  awaiting: 'confirmation' | 'detail' | null;
  error: string | null;
  elapsedMs: number | null;
  grounded: boolean | null;
  streaming: boolean;
}

export interface UserTurn {
  role: 'user';
  id: string;
  text: string;
}

export type Turn = UserTurn | AssistantTurn;

export function emptyAssistantTurn(id: string, query: string | null = null): AssistantTurn {
  return {
    role: 'assistant',
    id,
    query,
    status: null,
    prose: '',
    trace: [],
    ruleChecks: [],
    tier: null,
    intent: null,
    entities: {},
    answer: null,
    narrative: '',
    citations: [],
    confidence: null,
    unknowns: [],
    abstain: null,
    awaiting: null,
    error: null,
    elapsedMs: null,
    grounded: null,
    streaming: true,
  };
}
