# DATA_STORAGE_DESIGN.md

**Status: 🟡 PROPOSAL — not yet reflected in README §4/§11 or DECISIONS.md.**

This is a working draft of the Postgres-vs-vector-DB split discussed on 2026-09-04.
It does **not** override `DECISIONS.md` #1 ("no database") yet — that ADR stays the
source of truth until the team formally amends it. Treat this doc as the answer to
*"if/when we add storage, here is exactly what goes where and why,"* derived from the
real dataset schema rather than the abstract discussion.

Owner: Kashifa (finalizing the split, per team notes). Vector DB product choice: Shashank
(see candidate shortlist in §4 below for input).

---

## 1. Principle

> Structured, exactly-queryable operational facts → **Postgres**.
> Free-text / narrative / "what happened and why" content that benefits from semantic
> retrieval → **vector DB**.

Risk signals are the test case for this principle: they are structured (a float score +
a list of driver strings) and the answer keys never ask "find me risk signals *like*
this one" — they ask "what is C-1042's score." That's an exact lookup, so risk signals
stay in Postgres, reformatted for display, with **no embedding, no semantic search**.

---

## 2. Postgres — structured operational truth

One table per vendored JSON file, mapped directly (no invented normalization beyond
what the source data already implies):

| Table | Source | Key fields | Notes |
|---|---|---|---|
| `crew` | `crew.json` | `crew_id` (PK), `name`, `rank`, `base`, `ratings[]`, `seniority`, `reachability_minutes`, `status` | `ratings` as a text array or a join table if you want per-rating queries |
| `flights` | `flights.json` | `flight_id` (PK), `flight_no`, `date`, `dep_station`, `arr_station`, `dep_utc`, `arr_utc`, `block_hours`, `aircraft`, `aircraft_type`, `seats` | |
| `certifications` | `certifications.json` | `(crew_id, cert_type)` composite key, `valid_from`, `valid_to` | 600 rows now (4 types × 150 crew); RULE-CERT-06 does a straight date-range check |
| `duty_clocks` | `duty_clocks.json` | `crew_id` (PK), `as_of_utc`, `duty_hours_7d`, `flight_hours_28d`, `last_rest_ended` | roll-up columns |
| `duty_daily_history` | `duty_clocks.json[].daily_history` | `(crew_id, date)` composite key, `duty_hours`, `flight_hours` | one row per crew per day, 28 days × 150 crew = 4,200 rows. This is what RULE-DUTY-02/FLT-03's calendar-day window math sums over — keep it queryable by date range, don't collapse it into JSONB if you want plain SQL window sums |
| `reserve_pool` | `reserve_pool.json` | `crew_id` (PK), `base`, `dates[]`, `oncall_window_utc.start/end` | 16 rows |
| `pairings` | `rosters.json.pairings` | `pairing_id` (PK), `aircraft` | 39 rows |
| `pairing_days` | `rosters.json.pairings[].days` | `(pairing_id, date)`, `flights[]`, `report_utc`, `release_utc` | |
| `pairing_crew` | `rosters.json.pairings[].crew` | `(pairing_id, crew_id)`, `role` | |
| `roster_exceptions` | `rosters.json.flagged_exceptions` | `crew_id`, `date`, `rule`, `note` | structured mirror of the exception — see §3 for why the *note itself* also belongs in the vector DB |
| `costs` | `costs.json` | single-row reference/config table | `reserve_callout_pilot`, `deadhead_positioning`, `cancellation_per_flight`, etc. — small enough to also just be an in-app constant, but a table lets ops update rates without a redeploy |
| `risk_signals` | `risk_signals.json` | `crew_id` (PK), `as_of_utc`, `disruption_risk_score`, `drivers[]` | **provided input — do not build prediction on top of this** (dataset README is explicit). Whole rows, no embedding. |

If/when airport-level data gets fabricated (gates, weather state, repair schedules,
nearby-diversion lists — see the "only one real airport" finding below), it goes here
too: it's structured filterable fact, not narrative.

---

## 3. Vector DB — semantic retrieval over rules, precedent, and narrative

Four collections, each addressing a real "find something *like* X" need that Postgres
filtering can't do well:

| Collection | Source | Why it's semantic, not exact | Query shape |
|---|---|---|---|
| `Rules` | `rules.json` | Controllers ask in plain English ("what's the rest requirement?") not by rule ID | embed `text` + prose gloss; keep `rule_id` and `params` as filterable metadata for the exact-match path |
| `ScenarioPrecedent` | `scenarios.json` (6 now, `internal/held_out_scenarios.json` locked, and — over time — real resolved incidents) | "has something like this happened before" is inherently a similarity question over narrative/reasoning text | embed `event.narrative` + `answer_key.options[].reasoning` + `answer_key.expected_choice.reasoning` + `answer_key.note` (scenario-level clarifications, e.g. S6's equal-cost-mirror note) concatenated per scenario; keep the rest of `answer_key` (options, costs, ranks) as metadata payload, not embedded — it's structured, retrieved not searched |
| `ControllerNote` | `rosters.json.flagged_exceptions` today (1 row); the real target is free-text controller notes/overrides as they accrue in production | today's `flagged_exceptions` entry is basically a structured audit fact, but the category this collection models — "why did a controller override X" — is unstructured and will grow. Mirror the current exception into Postgres (§2) for exact lookup, embed the `note` text here for the "find similar past overrides" use case | embed `note`; metadata: `crew_id`, `date`, `rule` |
| `IntentExample` | `questions.json` (38 rows) | used for few-shot intent routing / semantic question matching in the agent's router — not shown to controllers directly | embed `prompt` + `explanation` + `expected_answer.reasoning` (where present); metadata: `tier`, `rules_ref[]` |

**`risk_signals.json` is deliberately excluded from the vector DB.** It's whole
structured rows, exact-queried, reformatted for display — no embedding, per the
principle in §1. (An earlier draft of the team notes listed it under both stores; this
resolves that to Postgres-only, matching the explicit design call made separately.)

### 3a. What looks like a "note" but isn't vector-DB content

A full-field scan of every `note`/`notes`/`reason`/`reasoning`/`explanation` key in the
dataset turns up more hits than just `flagged_exceptions`. Two categories deliberately
stay out of the vector DB:

**Deterministic rule-verdict text — never embed this.** `excluded_candidates[].reason`,
`excluded_dxa[].reason`, `excluded_dxb[].reason`, and `expected_answer.excluded_examples[].reason`
(e.g. *"RULE-DUTY-02: would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)"*) are
LEX's own computed output, not narrative precedent. They're already captured as ground
truth in `core/tests/fixtures/rule_test_matrix.json` for testing the rule engine's
output phrasing. If these were embedded and retrieved at answer time instead of
recomputed by LEX, the agent could surface a **stale or mismatched** exclusion reason —
exactly the failure mode the "LLM never calculates" trust boundary (README §2) exists
to prevent. LEX computes these live, every time; the vector DB never serves them.

**Dataset documentation — not controller notes, don't store as retrievable content at
all:**
- `costs.json.notes` — explains how to read the cost fields
- `rosters.json.note` (top-level, singular) — a dataset invariant statement ("every
  assignment is legal except flagged exceptions")
- `reserve_pool.json[].note` — the *identical* string repeated across all 16 rows,
  restating RULE-BASE-07 — redundant with `Rules`
- `questions.json` Q38's `expected_answer.note` — an eval-harness grading instruction
  ("open-ended, judged on reasoning"), not domain content

### 3b. One thing this scan resolved

`scenarios.json` S6's `answer_key.note` — *"The same crew member cannot cover both
pairings; the optimal plan minimises total cost across both. Equal-cost mirror
assignments (swapping which pairing each candidate covers) are equally correct."* —
directly answers the open team action item on clarifying optimal-joint-plan / equal-cost
mirror behavior in `scenarios.json`. It's already in the data; nothing further to derive.

---

## 4. Hybrid search config

Per the team decision: **BM25 weight 0.5 + semantic weight 0.5**, reranking added
later. This applies to queries against `Rules`, `ScenarioPrecedent`, `ControllerNote`,
and `IntentExample` — never against Postgres tables, which are exact-filtered.

Vector DB product shortlist (final pick is Shashank's call):

1. **Postgres + `pgvector`** (recommended) — same instance as §2, e.g. Neon/Supabase
   (both first-class on Vercel). Hybrid = one SQL query combining `ts_rank_cd()` (BM25-ish)
   with pgvector cosine distance at your own 0.5/0.5 weights. No second service, no
   second API key, no second thing to keep alive on demo day. Corpus here is a few
   hundred rows total — brute-force cosine is instant, ANN indexing is irrelevant at
   this scale.
2. **Weaviate Cloud** (already named in the team notes) — native `hybrid()` query with
   an `alpha` param that *is* your 0.5/0.5 split, plus built-in reranker modules so
   "add reranking later" is a config flag. Free sandbox tier covers this corpus easily.
   Trade-off: a second managed service to provision, secure, and depend on at demo time.
3. Not recommended here: Pinecone/Qdrant — their hybrid modes need hand-built sparse
   (SPLADE-style) vectors to approximate BM25, which is more engineering for the same
   result you get natively from either option above.

---

## 5. PII

No PII fields (phone/email/address) exist anywhere in the current dataset — `crew.json`
has only `crew_id, name, rank, base, ratings, seniority, reachability_minutes, status`.
Nothing to redact today. If PII gets added later (per the team's redaction-layer note):

- Structured PII columns in Postgres → mask/tokenize at the ingestion layer, before the
  row is ever queryable by the agent's tools.
- **Never embed PII into the vector DB.** Embeddings are not reversible in the way a
  masked column is, but they still leak information through similarity search — treat
  "don't embed raw PII" as a hard rule, not a nice-to-have.

---

## 6. Open question this doc does not settle

Whether the team formally moves off `DECISIONS.md` #1 ("no database, in-memory
`World`"). This document assumes storage gets added but doesn't argue the case either
way — that's the README/DECISIONS update to make later, per the team's own call to
defer it.
