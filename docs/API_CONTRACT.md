# API_CONTRACT.md

**Status: 🟡 DRAFT — freeze before implementation starts.**

This is the seam the whole team codes against. Once frozen, changing it requires a note in `DECISIONS.md` and a heads-up to all four of us — because Kiran, Shashank and the harness are all building against it simultaneously.

**Fixtures live in `evals/fixtures/` and are lifted from the answer keys — so the mocks are already the correct answers.** Build against them freely; the mock→real swap is a no-op if both sides pass `evals/contract_test.py`.

---

## Conventions

- Base: `/api/v1` · JSON in, JSON out · all times **ISO-8601 UTC** (`2026-09-15T05:00:00Z`)
- Money is integer INR. Hours are floats to 2dp.
- Every response carries `trace` — the tool calls that produced it. **The UI renders this. It is not debug output.**

---

## `POST /api/v1/ask` — the main entry point

```jsonc
// request
{ "query": "Captain C-1042 called in sick for P-2291. Who do I use?",
  "as_of": "2026-09-15T05:00:00Z",      // optional; defaults to snapshot
  "weights": { "cost": 1.0, "delay": 1.0, "pool": 0.5, "pairing": 0.8, "fairness": 0.3 },
  "stream": true }
```

```jsonc
// response — the typed answer object. Prose is RENDERED FROM this, never the reverse.
{ "tier": 2,
  "intent": "FIND_REPLACEMENT",
  "entities": { "crew_id": "C-1042", "pairing_id": "P-2291", "role": "Captain" },
  "answer": { /* tier-specific — see below */ },
  "narrative": "C-3310 is your cleanest option …",
  "citations": [ { "kind": "rule", "id": "RULE-DUTY-02" },
                 { "kind": "record", "source": "duty_clocks.json", "id": "C-2087" } ],
  "confidence": "high",                  // high | medium | low
  "unknowns": [],
  "trace": [ { "tool": "find_options", "args": {...}, "ms": 12 } ] }
```

### Streaming (`stream: true`)
`text/event-stream`. Kiran needs **both** kinds of event:

```
event: tool_call    data: {"tool":"check_legality","args":{"crew_id":"C-2087"}}
event: tool_result  data: {"tool":"check_legality","verdicts":[...]}
event: token        data: {"text":"C-3310 is "}
event: done         data: {"answer":{...}}
```

---

## Tier-specific `answer` shapes

### Tier 1 — Lookup
```jsonc
{ "kind": "lookup", "rows": [ ... ], "count": 7 }
```

### Tier 2 — Replacement
```jsonc
{ "kind": "replacement",
  "uncovered_flights": ["DX412-2026-09-15", "DX413-2026-09-15", "DX588-2026-09-15"],
  "at_risk_flights":   ["DX589-2026-09-16"],
  "passengers_affected": 486,
  "funnel": [                                  // ← rendered in the evidence rail
    { "stage": "all_crew",   "count": 150 },
    { "stage": "role",       "count": 32,  "dropped": 118, "reason": "not Captain" },
    { "stage": "qualified",  "count": 21,  "dropped": 11,  "reason": "RULE-QUAL-05 / status" },
    { "stage": "available",  "count": 12,  "dropped": 9,   "reason": "duty conflict" },
    { "stage": "legal",      "count": 6,   "dropped": 6,   "reason": "rule breach" }
  ],
  "options":    [ /* Option[] — ranked */ ],
  "near_misses":[ /* Option[] with `unlock` set */ ],
  "excluded":   [ { "crew_id": "C-2087", "verdicts": [ /* RuleVerdict[] */ ] } ] }
```

### Tier 3 — Consequence / recommendation
```jsonc
{ "kind": "consequence",
  "options": [ /* Option[] */ ],
  "blast_radius": { "nodes": 6, "flights": 3, "aircraft": 1, "passengers": 486,
                    "edges": [ { "from": "C-1042", "to": "DX412-2026-09-15",
                                 "kind": "direct" } ] },
  "world_diff": { "before": {...}, "after": {...}, "changed": [...] },  // SANDBOX
  "joint_plan": { "total_cost_inr": 42500, "assignments": {...},
                  "equal_cost_alternatives": 20 } }                      // JOINT / S6
```

> **Ties are first-class.** S6 has **20 equally-optimal assignments** (ten captains at ₹24,000 × two interchangeable pairings). dCortex: *"Equal-cost mirror assignments … are equally correct."*
> The harness scores `total_cost_inr` + feasibility (both legal, crew IDs distinct) — **never `crew_id`**. Surface `equal_cost_alternatives` so the UI can tell the controller *"19 other assignments cost the same"* rather than implying a single forced answer.

---

## Shared types

```jsonc
// Option — matches the answer-key shape exactly. Do not rename these fields.
{ "action": "Assign Captain C-3310 (reserve callout)",
  "crew_id": "C-3310",
  "legal": true,
  "rules_checked": ["RULE-FDP-01","RULE-DUTY-02","RULE-FLT-03",
                    "RULE-REST-04","RULE-QUAL-05","RULE-CERT-06","RULE-BASE-07"],
  "cost_inr": 18500,
  "delay_hours": 0.0,
  "rank": 1,
  // our additions beyond the key — additive only, never replacing the above
  "cost_breakdown": { "callout": 18500, "positioning": 0, "delay": 0 },
  "blast_radius": 0,
  "verdicts": [ /* RuleVerdict[] */ ],
  "unlock": null }        // near-miss only, e.g. "legal if departure slips ≥35 min"

// RuleVerdict
{ "rule_id": "RULE-DUTY-02", "status": "FAIL",
  "detail": "would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)",
  "used": 61.33, "limit": 60.0, "headroom": -1.33, "date": "2026-09-15" }
```

> **`Option` keeps the answer-key field names verbatim** (`action`, `crew_id`, `legal`, `rules_checked`, `cost_inr`, `delay_hours`, `rank`). The harness compares against them directly. Add fields; never rename or remove.

---

## Tool surface (L2, behind the trust boundary)

Coarse and semantically meaningful — not micro-CRUD. The agent calls these; it never computes.

| Tool | Args | Returns |
|---|---|---|
| `lookup` | `entity`, `filters` | rows — Tier-1 workhorse |
| `duty_clock` | `crew_id`, `date` | 7d/28d sums, headroom, `last_rest_ended` |
| `check_legality` | `crew_id`, `pairing_id`, `delay_h?` | `RuleVerdict[]` — all 7 rules |
| `find_options` | `pairing_id`, `role`, `callout_utc` | funnel + ranked `Option[]` + excluded |
| `simulate` | `event` | `world_diff` + consequences (SANDBOX) |
| `ripple` | `event` | `blast_radius` |
| `joint_plan` | `events[]` | cost-minimal joint assignment |
| `explain_rule` | `rule_id` | rule text + params + plain-English gloss |

---

## Supporting endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/scenarios` | S1–S6 for the scenario feed |
| `POST` | `/api/v1/scenarios/{id}/run` | run a scenario end-to-end |
| `POST` | `/api/v1/rank` | re-rank existing options with new `weights` (slider path — must be fast, no LLM) |
| `GET` | `/api/v1/rules` | all 7 rules with params |
| `GET` | `/api/v1/health` | `{ "world_loaded": true, "crew": 150, "flights": 147 }` |

---

## Errors

```jsonc
{ "error": { "code": "UNRESOLVED_ENTITY",
             "message": "No pairing 'P-9999' in the roster.",
             "hint": "Did you mean P-2291?" } }
```

Codes: `UNRESOLVED_ENTITY` · `AMBIGUOUS_QUERY` · `NO_LEGAL_OPTION` · `OUT_OF_SCOPE` · `INTERNAL`

**`NO_LEGAL_OPTION` is a real answer, not a failure** — return it *with* `near_misses` populated. "Nobody is legal, but a 35-minute delay unlocks Sharma" is the most valuable thing the advisor can say.
