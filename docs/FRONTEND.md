# Frontend integration

For Kiran. What the agent returns, what you must render, and the one thing
that will catch you out.

Architecture and rationale: [`HOW_IT_WORKS.md`](HOW_IT_WORKS.md).
Setup: [`SETUP.md`](SETUP.md).

---

## 1. Start here

```bash
AGENT_DATA=core AGENT_LLM=anthropic python -m devui.server
```

`http://localhost:8420` is a working reference implementation of everything
below. It is a dev tool, not the product — but when a shape is unclear, look at
what it does with it. CORS is open, so an Angular dev server on `:4200` can
call it directly.

Base URL is `http://localhost:8420/api/v1`. `api/` (the production Flask app,
issue #32) will serve the same paths.

---

## 2. The one thing that will catch you out

**An answer can be a question.** The agent asks the controller things:

> C-2087 is a Captain, not a First Officer. Did you mean a different crew
> member, or shall I proceed with C-2087 as Captain?

> DX412 operates on 2026-09-15, 2026-09-17, 2026-09-19. Which date do you mean?

These arrive as a normal `200` with `awaiting` set. **Check it before you
render anything else:**

```ts
if (res.awaiting) {
  // A prompt expecting a reply — not a finding. There is no recommendation,
  // no funnel and no options to draw.
  showPrompt(res.narrative);          // "confirmation" | "detail"
} else {
  renderAnswer(res);
}
```

The controller's next message answers it. `yes` / `no` / a corrected id / a
date all work, because the server holds the conversation. **Do not clear the
input or start a new thread on these** — the reply must be the next turn.

Treating a question as an answer is the worst failure available here: the UI
would show an empty recommendation panel and the controller would read it as
"nothing to do".

---

## 3. `POST /api/v1/ask`

```jsonc
// request
{ "query": "C-1042 is sick" }
```

```jsonc
// response
{
  "tier": 2,                          // 1 lookup · 2 replacement · 3 consequence
  "intent": "FIND_REPLACEMENT",
  "awaiting": null,                   // ← check this first (§2)
  "confidence": "high",               // high | medium | low
  "entities": { "crew_ids": ["C-1042"] },
  "narrative": "Take C-3310 on reserve callout…",   // prose, ready to show
  "answer": { /* typed body, see §4 */ },
  "citations": [{ "kind": "rule", "id": "RULE-DUTY-02" }],
  "unknowns": ["…"],                  // caveats — render them, see §6
  "trace": [{ "tool": "find_options", "args": {…}, "ms": 12, "error": null }]
}
```

`narrative` is the answer a controller reads. `answer` is the same information
structured, for the panels. They always agree — the prose is rendered from the
object, never the other way round.

---

## 4. The `answer` body

`answer.kind` tells you which shape you have.

### `kind: "lookup"` — tier 1
```jsonc
{ "kind": "lookup", "rows": [ { … } ] }
```
A table. Column names come from the data.

### `kind: "replacement"` — tier 2, the main one
```jsonc
{
  "kind": "replacement",
  "recommended": { "action": "Assign Captain C-3310 (reserve callout)",
                   "crew_id": "C-3310", "cost_inr": 18500, "delay_hours": 0.0 },
  "options": [ /* ranked, includes a cancel option with crew_id: null */ ],
  "excluded": [ { "crew_id": "C-2087",
                  "reason": "would exceed 60h/7d by 1h20m on 2026-09-15",
                  "rules": ["RULE-DUTY-02"] } ],
  "funnel": [ { "stage": "considered", "count": 27, "dropped": 0, "reason": "" },
              { "stage": "qualified",  "count": 16, "dropped": 11,
                "reason": "no rating / not active" } ],

  "uncovered_flights": ["DX412-2026-09-15", …],   // grounded now
  "at_risk_flights":   ["DX589-2026-09-16", …],   // downstream, day 2+
  "passengers_affected": 486,                      // see the caveat below

  "cancellation_multiple": 81,       // cancel costs 81x the recommendation
  "next_tier_premium_inr": 5500,     // gap to the next-cheapest option
  "equal_cost_alternatives": 0,      // >0 means the pick is NOT unique

  // A direct legality question answers here instead of with candidates:
  "subject": "C-2087", "legal": false,
  "verdicts": [ { "rule_id": "RULE-DUTY-02", "status": "FAIL",
                  "detail": "would exceed 60h/7d by 1h20m on 2026-09-15",
                  "used": 61.33, "limit": 60.0, "headroom": -1.33 } ]
}
```

> **`passengers_affected` is seat capacity, not bookings.** The dataset has no
> load data, so it is the sum of `seats` on the affected legs. dCortex's answer
> key uses the same figure under the same name, so the field keeps it — but
> **label it "seats at risk" in the UI.** "486 passengers" across three A320s is
> exactly 100% load, and a controller will spot that immediately.

### `kind: "consequence"` — tier 3
```jsonc
{
  "kind": "consequence",
  "options": [ … ],
  "blast_radius": { "nodes": 6, "flights": 6, "aircraft": 1, "passengers": 486,
                    "edges": [ { "from": "P-2291", "to": "DX412-2026-09-15",
                                 "kind": "direct" } ] },
  "joint_plan": { "total_cost_inr": 42500, "equal_cost_alternatives": 20,
                  "assign_P-2205": { … }, "assign_P-2212": { … } },
  "world_diff": { "changed": [ … ] }
}
```

---

## 5. What to build, in order

**1 — Chat + narrative.** Handle `awaiting` (§2). This alone is usable.

**2 — Recommendation card.** `answer.recommended`: the action, the cost, the
delay. Lead with it. If `equal_cost_alternatives > 0`, say so — several plans
cost the same and presenting one as uniquely right is wrong.

**3 — Candidate funnel.** `answer.funnel` — `27 → 16 → 7 → 5` with the reason
for every drop. **This is the single most valuable panel.** It is what makes
the recommendation auditable, and no other team will have it.

**4 — Rule trace.** `answer.verdicts`, or `excluded[].rules`. Show
`used / limit / headroom`, not just PASS/FAIL. A controller needs to know a
breach is 1h20m, because that is actionable and "illegal" is not.

**5 — Cost contrast.** `cancellation_multiple`. Frame cancelling as the
counterfactual, not as option #6 — ₹1,500,000 against ₹18,500 is not a ranking.

**6 — Verifier ledger.** From `trace` (§6). The trust story, made visible.

**7 — Blast radius.** `blast_radius.edges` — a graph or a list. `kind` is
`"direct"` or `"orphaned-day"`; the second is the interesting one, because
crew fly whole pairings and losing day 1 strands day 2.

---

## 6. Fields that look like debug output and are not

**Do not filter these out.** They look internal and they are the product.

| Field | Why it matters |
|---|---|
| `trace` | Every tool call, its arguments and result. The evidence rail renders it. |
| `citations` | Rules and records the answer rests on. |
| `confidence` | `low` means a tool failed. Show it. |
| `unknowns` | Caveats in plain English, e.g. *"the model's draft claimed 12.4, which no tool output supports — that draft was discarded"*. |

That last one is worth understanding. Every claim in the prose is checked
against the tool results before it ships. When the check fails, the model's
draft is thrown away and the verified template is sent instead — and the reason
lands in `unknowns`. **Render it.** It is the system catching a fabrication in
the open, which is the most convincing thing it does.

---

## 7. Streaming

`GET /api/v1/stream?q=…` — SSE, for the live reasoning trace.

```
event: tool_call    data: {"tool":"find_options","args":{…}}
event: tool_result  data: {"tool":"find_options","ms":12,"error":null}
event: token        data: {"text":"Take C-3310 "}
event: done         data: {"answer":{…}}
```

`tool_call` / `tool_result` are what let a controller watch the work happen —
RxJS `scan` them into a running list. Use `POST /ask` for the final object;
streaming is for the trace, not the source of truth.

---

## 8. Supporting endpoints

| | |
|---|---|
| `GET /api/v1/health` | which model and data backend are live |
| `GET /api/v1/state` | detail: which of the 8 tools are live |
| `GET /api/v1/questions` | the 38 gold questions, for a demo rail |
| `GET /api/v1/scenarios` | S1–S6 with their answer keys |
| `GET /api/v1/scenarios/{id}` | one scenario in full |
| `GET /api/v1/rules` | all 7 rules with parameters |
| `GET /api/v1/reset` | clear the conversation |

---

## 9. Errors

```jsonc
{ "error": { "code": "UNRESOLVED_ENTITY",
             "message": "There is no crew C-1045…",
             "hint": "…" } }
```

Codes: `UNRESOLVED_ENTITY` · `NEEDS_CONFIRMATION` · `AMBIGUOUS_QUERY` ·
`NO_LEGAL_OPTION` · `OUT_OF_SCOPE` · `INTERNAL`.

**`NEEDS_CONFIRMATION` and `AMBIGUOUS_QUERY` arrive as `200` with `awaiting`
set, not as errors** — they are questions, and the flow continues.

**`NO_LEGAL_OPTION` is a real answer, not a failure.** It comes with
`near_misses` populated: *"nobody is legal, but a 35-minute delay unlocks
Sharma"* is the most valuable thing the system says. Do not render it as an
error state.

---

## 10. Conversation

The server holds one session and resolves follow-ups against it:

```
"C-1042 is sick"        → ranked options
"why not C-2087?"       → the exclusion reason, no new tool call
"what about C-2210?"    → legal, ranked #5, ₹41,200, 3h delay
"go with C-3310"        → recorded
```

Send each turn as a plain `POST /ask`. Nothing extra is needed from you —
just do not reset between them, and keep `awaiting` replies in the same thread.

The production API will key sessions per user; today it is one conversation
per server process, cleared by `GET /reset`.

---

## 11. Practical notes

- **Latency is 2–25s** on `claude-opus-5` — a tier-3 question makes several
  model calls. Stream, or show the tool trace as progress. Do not spin blankly.
- **Answers are not idempotent.** Prose varies between runs; the `answer`
  object does not. Key your UI off the object.
- **Money is integer INR** (`18500` → `₹18,500`). **Times are UTC**, always.
- **Never rename an `Option` field.** `action`, `crew_id`, `legal`,
  `rules_checked`, `cost_inr`, `delay_hours`, `rank` are the answer-key
  contract — the eval harness compares against them.

## 12. If something is wrong

Reproduce it with `#q=<url-encoded question>` on the dev console and send the
link — it re-runs the exact query. Typing real questions at it has found more
defects than any test suite here, so a bad answer is worth reporting rather
than working around.
