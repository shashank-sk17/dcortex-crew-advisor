# Contract reconciliation — read this before hour 1

**Status: 🟡 PROPOSAL — Shashank to ratify, then fold into `API_CONTRACT.md` and stamp FROZEN.**

Two contracts existed going into the hackathon:

| | `docs/API_CONTRACT.md` (repo, Shashank) | Pre-built Angular starter (`crew-ops-advisor-ui`) |
|---|---|---|
| Transport | `POST /api/v1/ask` `{query, as_of, weights, stream}` | `GET /api/ask/stream?q=` EventSource |
| SSE events | `tool_call`, `tool_result`, `token`, `done` | `status`, `tool_call`, `tool_result`, `rule_check`, `token`, `answer`, `abstain`, `done`, `error` |
| Answer | rich typed object — `funnel[]`, `near_misses[]`, `excluded[]`, `blast_radius`, `confidence`, `unknowns`, `citations` | simpler `payload` — Tier1 table / Tier2 `impact` / Tier3 `options` |
| Abstain | `NO_LEGAL_OPTION` error code | first-class `abstain` event + card |

Both encode the same architectural bet (LLM narrates, deterministic code computes). This note picks one and keeps the best of both.

---

## Decisions

### 1. Transport — `POST /api/v1/ask` wins
The repo contract's POST body carries `weights` (policy sliders) and `as_of`. `EventSource` cannot POST, so the frontend reads the stream with `fetch()` + a `ReadableStream` reader instead. No functional loss; the starter's `EventSource` code is replaced.

### 2. Answer object — the repo's rich object wins
It keeps the **answer-key field names verbatim** (`action, crew_id, legal, rules_checked, cost_inr, delay_hours, rank`), which `evals/harness.py` compares against directly. The starter's simpler `impact` / `options` shapes are a strict subset — the evidence rail needs the funnel and the excluded-candidate list, which only the repo object has.

### 3. Three events adopted from the starter — **additive, non-breaking**

| Event | Why it earns its place |
|---|---|
| `status` `{ text }` | Cheap UX win — "Resolving station and date…" while tools run. Non-load-bearing; a controller never acts on it. |
| `rule_check` `{ rule_id, subject, status, detail, used?, limit?, headroom?, margin?, date? }` | The 7-rule legality trace in the evidence rail renders these as they stream, one per rule, instead of waiting for the whole `answer`. Superset of the repo's `RuleVerdict`. |
| `abstain` `{ reason, needed[] }` | The brief **scores** "I can't answer that reliably" over a confident wrong answer (§7 scoring principles, deliverable #6). Promoting it from an error code to a first-class event + card makes that visible to judges without a word of narration. |

`done` gains `grounded: boolean` — the verifier's verdict that every number in the prose traced to a `tool_result`. This is the anti-hallucination gate made visible.

---

## The reconciled event stream (v1)

`POST /api/v1/ask` `{ query, as_of?, weights?, stream: true }` → `text/event-stream`, one JSON event per `data:` line.

```jsonc
status       { "text": "Enumerating legal coverage options…" }
tool_call    { "id": "t1", "tool": "find_options", "args": { "pairing_id": "P-2291", "role": "Captain", "callout_utc": "2026-09-15T05:00:00Z" } }
tool_result  { "id": "t1", "tool": "find_options", "summary": "150 → 6 legal (+2 near-miss)", "data": { ... }, "ms": 14 }
rule_check   { "rule_id": "RULE-DUTY-02", "subject": "C-2087", "status": "FAIL",
               "detail": "would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)",
               "used": 61.33, "limit": 60.0, "headroom": -1.33, "date": "2026-09-15" }
token        { "text": "C-3310 is " }
answer       { "tier": 2, "intent": "FIND_REPLACEMENT", "entities": {...},
               "answer": { /* tier-specific, see API_CONTRACT.md §"Tier-specific answer shapes" */ },
               "narrative": "…", "citations": [...], "confidence": "high", "unknowns": [] }
abstain      { "reason": "No field in the dataset supports this.", "needed": ["live METAR feed", "passenger-level records"] }
done         { "elapsed_ms": 1900, "grounded": true }
error        { "code": "UNRESOLVED_ENTITY", "message": "No pairing 'P-9999'.", "hint": "Did you mean P-2291?" }
```

Non-streaming (`stream` omitted/false): single JSON response body = the `answer` event's object, plus `trace: [{tool, args, ms}]`.

Supporting endpoints unchanged from `API_CONTRACT.md`: `GET /health`, `GET /scenarios`, `POST /scenarios/{id}/run`, `POST /rank`, `GET /rules`.

---

## What this means per person

- **Shashank** — emit the stream above. `status`/`abstain` are yours to decide when to send; `rule_check` you forward straight from `check_legality`'s verdicts as they come back. Ratify or push back on this doc, then stamp `API_CONTRACT.md` FROZEN.
- **Kiran** — `frontend/` already builds to this (`src/app/models/agent-events.ts`). Mock in `api/mock.py` emits it. `environment.useMock=false` is the only integration step.
- **Kashifa / Gayathri** — unaffected. Your tool outputs are wrapped into `tool_result` / `rule_check` by the agent layer; `Option` and `RuleVerdict` field names are unchanged.

Frozen reference emitter: **`api/mock.py`** (replaces the starter's `contract/mock_backend.py`).
