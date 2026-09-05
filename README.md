# dCortex Crew Ops Advisor

An AI advisor for the airline crew control desk. A controller asks a question in plain English — *"Captain C-1042 just called in sick for P-2291, who do I use?"* — and gets a legally-verified, cost-ranked, fully-cited answer in seconds instead of twenty minutes of manual cross-referencing.

**Team:** Shashank · Kiran · Kashifa · Gayathri
**Carrier:** dCortex Air (synthetic) · **Hub:** BLR · **Week:** 2026-09-14 → 2026-09-20 · **All times UTC · Currency INR**

---

## 1. The problem

Crew control is the highest-pressure desk in an airline. A captain calls in sick at 05:00 and the controller must, right now, find a replacement who is qualified, legal, rested, in the right place, and free. Today they do it by hand — cross-referencing rosters, duty blocks, a reserve list and a dense regulatory rulebook, under time pressure, while the aircraft sits on stand.

We build the advisor that does that reasoning with them. It must answer three tiers of question:

| Tier | Question type | Example |
|---|---|---|
| **1 — Lookup** | Retrieve a fact | *"Who is on reserve at BLR on 15 Sep, and what are their windows?"* |
| **2 — Replacement** | Find and verify a substitute | *"If Captain C-2087 covers P-2291, does any rule break?"* |
| **3 — Consequence** | What-if, cascade, recommendation | *"C-1042 is out for P-2291. Produce ranked resolution options with costs."* |

And it must be **trusted**. An answer a controller cannot audit is worthless.

---

## 2. The one architectural decision everything hangs on

Most teams will point an LLM at the rulebook and let it answer. That fails here in exactly the way that matters — a controller cannot act on a number that might have been invented.

> ### The LLM **selects, sequences and narrates.** It never **calculates.**
>
> Every number, name, verdict and rule citation in an answer originates from a deterministic tool call. The model's job is to understand the question, choose the right tools, and explain the evidence in the controller's language. Nothing else.

This puts a hard **trust boundary** at the tool interface:

- **Below it** — pure Python. Testable, reproducible, scored against dCortex's own answer keys. Zero hallucination surface.
- **Above it** — the flexible natural-language layer.

It is our strongest story for the judges, and it is also what lets four people build in parallel without blocking each other.

---

## 3. What the dataset told us

We profiled all 12 files in [`crew-ops-advisor-dataset/`](crew-ops-advisor-dataset/) before designing anything. Four findings drove every decision below.

### ① It is small — so the infrastructure stays small

| Entity | Count | | Entity | Count |
|---|---|---|---|---|
| Crew | 150 | | Rules | **7** |
| Flights | 147 | | Scenarios (with answer keys) | 6 |
| Pairings | 39 | | Gold questions | 38 |
| Reserves | 16 | | **Total dataset** | **< 700 KB** |

The entire world fits in memory with room to spare. **No Postgres, no Neo4j, no MongoDB, no Celery.** They would cost the better part of a day in schema, loaders and Docker wrangling and buy us nothing at this scale. The core is plain Python dataclasses behind one `World` object.

If you are used to reaching for a database, resist it here. The constraint is *correctness under time pressure*, not throughput.

### ② Answer keys are structured JSON — so we can score ourselves exactly

```json
{ "legal": false,
  "issues": ["RULE-DUTY-02: would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)"] }
```

All 38 questions and 6 scenarios are machine-comparable. That means:

- The eval harness is not a nice-to-have — **it is how we prove the thing works**, and it runs in CI on every push.
- The agent must emit a **typed answer object** per tier, with prose *rendered from it*. Never prose first.

### ③ Ranking is cost-deterministic, not fuzzy

The answer keys rank options by `(legal, cost_inr, delay_hours)` against a fixed rate card:

| Action | Cost (INR) |
|---|---|
| Reserve callout — pilot | 18,500 |
| Reserve callout — cabin | 9,500 |
| Day-off callout — pilot | 24,000 |
| Day-off callout — cabin | 12,500 |
| Deadhead positioning | +6,500 |
| Delay | +5,400 per duty hour |
| **Cancellation** | **250,000 per leg** |
| Hotel overnight | 4,200 |

So our ranker's default configuration must **reproduce the answer keys exactly**. That is a correctness bar, not a design preference.

### ④ Scenario S6 needs a disjointness constraint — and has 20 correct answers

> *"Both A320 captains (VT-DXA and VT-DXB) are sick at 00:30Z on 18 Sep. Give the **optimal joint** crewing plan."* — key: `total_cost_inr: 42500`

`options_dxa` and `options_dxb` are near-identical lists — C-3305 is rank 1 in **both**, C-1017 rank 2 in **both**. Solve each aircraft independently and you assign C-3305 to both for ₹37,000. That is **infeasible**, not merely suboptimal: one person cannot fly two aircraft at once.

The optimal plan is C-3305 (reserve, ₹18,500) on one pairing and any ₹24,000 day-off captain on the other.

**And there are 20 correct answers, not one.** Ten captains sit at exactly ₹24,000, and the two roles are interchangeable — dCortex says so outright: *"Equal-cost mirror assignments (swapping which pairing each candidate covers) are equally correct."* So:

> ⚠️ **The harness must never compare `crew_id` on S6/Q32.** Score `total_cost_inr == 42500` **+** both legal **+** the two crew IDs distinct. Comparing identities marks 19 of the 20 correct answers wrong.

Note we are *not* claiming greedy fails here — sequential greedy that removes the assigned crew gets ₹42,500, because the cost structure is flat (one cheap reserve, then a plateau). We build proper assignment for **robustness**: the held-out scenarios may not be flat, and Hungarian over a small cost matrix is ~10 lines.

---

## 4. Architecture

```
                       ┌──────────────────────────────────────────┐
                       │   CREW CONTROLLER  (human, in the loop)  │
                       └─────────────────────┬────────────────────┘
                                             │ natural language + clicks
┌────────────────────────────────────────────▼─────────────────────────────────┐
│  L4   OPS CONSOLE              Angular + RxJS + SSE              ◆ KIRAN     │
│  ┌─────────────┬──────────────────────────┬───────────────────────────────┐  │
│  │ Scenario    │  Conversation +          │  EVIDENCE RAIL                │  │
│  │ Feed        │  Answer Cards            │   · candidate funnel          │  │
│  │ S1…S6 +     │  (streamed tokens AND    │   · 7-rule legality trace     │  │
│  │ free ask    │   live tool-call trace)  │   · blast radius + cost       │  │
│  │             │                          │   · policy weight sliders     │  │
│  └─────────────┴──────────────────────────┴───────────────────────────────┘  │
└────────────────────────────────────────────┬─────────────────────────────────┘
                     HTTP/JSON + SSE   ══════╪══════   FROZEN API CONTRACT
┌────────────────────────────────────────────▼─────────────────────────────────┐
│  L3   ADVISOR AGENT            Claude tool-use                 ◆ SHASHANK    │
│                                                                              │
│    ROUTER  ──►  PLANNER  ──►  TOOL LOOP  ──►  VERIFIER  ──►  EXPLAINER      │
│    tier 1/2/3   which          calls L2,      every claim     typed answer   │
│    + entities   tools, in      never          traced to a     object → prose │
│                 what order     computes       tool output     + citations    │
│                                                                              │
│         ▲  the LLM SELECTS, SEQUENCES, NARRATES — never CALCULATES  ▲        │
└────────────────────────────────────────────┬─────────────────────────────────┘
                       TOOL BOUNDARY   ══════╪══════   ← THE TRUST BOUNDARY
┌────────────────────────────────────────────▼─────────────────────────────────┐
│  L2   REASONING CORE — deterministic, unit-tested   ◆ KASHIFA + GAYATHRI     │
│                                                                              │
│   ┌────────┐  ┌────────┐  ┌────────┐  ┌─────────┐  ┌────────┐               │
│   │  LEX   │  │ RIPPLE │  │ JUDGE  │  │ SANDBOX │  │ JOINT  │               │
│   │ 7 rule │  │cascade │  │cost-   │  │what-if  │  │multi-  │               │
│   │ engine │  │ impact │  │optimal │  │world    │  │event   │               │
│   │+traces │  │        │  │ rank   │  │fork+diff│  │assign  │               │
│   └────┬───┘  └────┬───┘  └────┬───┘  └────┬────┘  └───┬────┘               │
└────────┼───────────┼───────────┼───────────┼──────────┼─────────────────────┘
┌────────▼───────────▼───────────▼───────────▼──────────▼─────────────────────┐
│  L1   OPS-GRAPH — in-memory typed world      ◆ KASHIFA                      │
│       crew · qual · cert · duty-clock · pairing · leg · aircraft · station   │
│       loaded from 12 JSON files · immutable base · copy-on-write forks       │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Why layered this way:** L1–L2 are pure functions of the dataset. They can be built, tested and *scored* with no LLM in the loop at all. L3 is swappable. L4 talks only to the frozen contract. Four people, four seams, no waiting.

---

## 5. The proprietary model — "the Cortex"

dCortex judges heavily on *how the AI builds its proprietary model*. Ours is five organs over one graph. None of it comes out of an API — we construct all of it.

### Substrate: `OPS-GRAPH`

Not a table dump — a model of how airline operations actually connect.

```
        (Crew)──HOLDS──►(Rating: A320 | ATR72)
          │  └──HOLDS──►(Certification)──valid_to──►(date)
          ├──ASSIGNED_TO──►(Pairing)──HAS_DAY──►(Day)──CONTAINS──►(Leg)
          │                    │                  │
          │                    └──ROTATES──►(Aircraft)      report / release
          ├──BASED_AT──►(Station)
          ├──HAS_CLOCK──►(DutyClock: 28d daily_history)
          └──ON_CALL──►(ReserveWindow: start–end UTC)
```

Crew fly **pairings**, not legs. `P-2291` is a two-day pairing that overnights at DEL. Encoding that as *structure* is what catches the failure most teams will ship: replace a captain on day 1 and silently strand day 2. Question Q17's answer key names exactly this (`day2_also_at_risk`).

### `LEX` — the legality engine

All 7 rules as individually-addressable predicates. Each returns a **verdict plus a trace**, never a bare boolean:

```
RULE-FDP-01   max FDP           PASS   11h15m used / 12h00m limit (4 sectors)
RULE-DUTY-02  60h / 7 cal-days  FAIL   61.33h — exceeds by 1h20m on 2026-09-15  ✗
RULE-FLT-03   100h / 28 days    PASS   64.27h / 100h
RULE-REST-04  min 12h rest      PASS   14h20m since last release
RULE-QUAL-05  type rating       PASS   A320 valid
RULE-CERT-06  certifications    PASS   all 4 valid on duty date
RULE-BASE-07  base / deadhead   PASS   BLR own-base reserve callout
```

Rules are **data** (params from `rules.json`), not code branches. Every FAIL is quotable to the controller and to an auditor.

**Two traps that will silently produce wrong answers — read `docs/RULES.md` before writing a line of this:**
1. `RULE-DUTY-02` and `RULE-FLT-03` windows are **calendar-day** based (UTC dates, inclusive of the duty date) — *not* rolling 168-hour windows.
2. `RULE-FDP-01` limit is `13h − 0.5h × (sectors − 2)`, so a 4-sector duty caps at 12.0h.

### `RIPPLE` — disruption impact propagation ← *the real IP*

Pulling one crew member is never a local event. Depth-limited traversal over OPS-GRAPH computes the **blast radius**:

```
  CPT C-1042 sick, pairing P-2291 ─┬─► DX412/413/588 15 Sep uncrewed ..... [direct]
                                   ├─► 486 passengers affected day 1 ..... [pax impact]
                                   ├─► DX589/590/591 16 Sep at risk —
                                   │     pairing overnights at DEL ....... [orphaned day 2]
                                   ├─► replacement pulled from own duty .. [2nd-order]
                                   ├─► DEL cover needs DX402 deadhead .... [positioning]
                                   ├─► BLR reserve depth 4 → 3 ........... [pool depletion]
                                   └─► VT-DXA rotation slips ~3h ......... [aircraft]
```

Tier 3 *is* RIPPLE. And scenario S4 requires it outright: a tech delay pushes the rostered crew past `RULE-FDP-01` on the tail legs, so **the delay itself creates a new crewing problem**. Cascade is not a flourish — it is a scored scenario.

### `JUDGE` — cost-optimal ranking

Legality is a **hard gate**. Everything that survives LEX is ranked by `(cost_inr, delay_hours)` off the rate card. Default config must reproduce every answer key exactly.

Layered on top: the same objectives exposed as **controller-adjustable weights** — cost, delay, reserve-pool preservation, pairing integrity, crew fairness. Move a slider, watch the ranking reorder live with fresh explanations. The AI advises; the human decides and keeps the wheel.

> **How we describe this to judges — do not overclaim.** Our ranking is *provably optimal against the published rate card*, not learned. At this data scale that is strictly better than a trained ranker, and it survives scrutiny. We log every controller accept/reject as a preference pair so weights *can* be learned once real usage data exists. Claiming a trained model we don't have is the fastest way to lose the room.

### `SANDBOX` — counterfactual world fork

Copy-on-write fork → apply perturbation → re-run LEX + RIPPLE → **diff the two worlds**. Covers all four event types in the dataset: `SICK_CREW`, station closure (S3), tech delay (S4), certification lapse (S5). Answers *"what if I delay 40 minutes instead?"* with a side-by-side, not a paragraph.

### `JOINT` — multi-event assignment

Simultaneous disruptions solved as **one** problem, under a hard **disjointness constraint** — the same crew cannot cover two pairings at once. Hungarian (or exhaustive; the sets are tiny) over the legal candidates, minimising total cost. This is what S6 scores.

---

## 6. The insight we are betting on

> *"finding the best possible replacement **or an outcome that allows all the downstream tasks**"* — the brief

dCortex is telling us **the answer is not always a person**. The dataset confirms it: S3 is a station closure, S4 a delay-induced breach, S5 a certification lapse. So our action space is deliberately wider than "pick a crew member":

```
 ASSIGN RESERVE ₹18.5k · DAY-OFF CALLOUT ₹24k · DEADHEAD +₹6.5k +delay
 DELAY DEPARTURE (buys legality) · SWAP PAIRING · RE-CREW TAIL LEGS · CANCEL ₹250k
```

Which unlocks the single highest-value behaviour in the product — **near-miss reporting**:

> *"No captain is legal at 06:00. But **C-2210 out of DEL becomes legal via the DX402 deadhead** — ₹41,200 all-in, DX412 departs ~3h late, zero cancellations. Versus ₹250,000 to cancel one leg."*

That is the judgement a twenty-year controller brings, and it is what separates an advisor from a search box. The dataset hands us this exact case. **It is a demo beat — build for it.**

---

## 7. How a Tier-2 request flows

```
 "Captain C-1042 called in sick for P-2291. Who do I use?"

 ROUTER ─► tier=2  crew=C-1042  pairing=P-2291  callout=2026-09-15T05:00Z
    │
    ▼  find_options()                          ── every drop is inspectable ──
        150  all crew
        ├─ 118 dropped   not Captain                              [ROLE]
         32  captains
        ├─  11 dropped   no A320 rating / on leave / training     [QUAL-05]
         21  qualified & active
        ├─   9 dropped   duty conflict — already rostered         [AVAIL]
         12  free
        ├─   6 dropped   rule breach — full trace attached        [LEX]
    ▼    6  LEGAL   (+2 NEAR-MISS: legal via deadhead / with delay)
    │
    ▼  JUDGE + RIPPLE per option
        #1  C-3310  reserve callout, BLR      ₹18,500   +0.0h   blast 0
        #2  C-1526  day-off callout           ₹24,000   +0.0h   blast 0
        #3  C-2210  deadhead DEL→BLR DX402    ₹41,200   +3.0h   blast 2
        ✗   C-2087  RULE-DUTY-02 +1h20m (61.33h vs 60h)
    │
    ▼  VERIFIER ── is every number above traceable to a tool output?
    │              ✓ → EXPLAINER      ✗ → re-query, never guess
    ▼
   Answer card: recommendation · why · rule citations · alternatives · risks
```

**The funnel renders in the UI.** Trust is inspectability — a controller believes what they can audit.

---

## 8. Team & responsibilities

| | Owner | Layer | Owns |
|---|---|---|---|
| 🧠 | **Shashank** | L3 — Advisor Agent | Router, planner, tool schemas, verifier, explainer, prompts. Owns the trust boundary. |
| 🎛 | **Kiran** | L4 — Ops Console | Angular, RxJS, SSE streaming, evidence rail, funnel + blast-radius visualisation. |
| ⚖️ | **Kashifa** | L1/L2 — World & Legality | `World` loader, duty math, **all 7 LEX rules**, cost model, **JOINT** optimiser. |
| 🌊 | **Gayathri** | L2 — Reasoning & Evals | **RIPPLE**, **SANDBOX**, and **owns the eval harness + scorecard**. |

### Shashank — Advisor Agent (L3)

You own the layer everyone judges. Concretely:

- **Router** — classify tier (1/2/3) and extract entities (crew ID, pairing, flight, date, callout time). Use Haiku 4.5 here; it's cheap and this is a classification job.
- **Tool schemas** — coarse and semantically meaningful, not micro-CRUD. Freeze these in `docs/API_CONTRACT.md` first; everything else keys off them.
- **Verifier** — the anti-hallucination gate. Before an answer ships, every number and every crew ID in it must be traceable to a tool output. If it isn't, re-query. Never guess. **This is the single feature that makes the demo credible.**
- **Explainer** — render the typed answer object into controller language. Structured object first, prose second, always.
- Model choice: Sonnet 5 for the tool loop, Haiku 4.5 for routing. Cache the system prompt + tool definitions — they're long and hit repeatedly.

### Kiran — Ops Console (L4)

- **Stream the reasoning, not just the answer.** SSE from the agent carrying both tokens *and* tool-call events; `scan` them into a live trace panel so the controller watches the AI work. Big trust win, and RxJS is made for this.
- **The evidence rail is the product.** Candidate funnel with drop reasons, the 7-rule trace, blast radius, cost breakdown. If someone can only see one panel, make it this one.
- **Policy sliders** — debounced re-rank on change, live reorder with fresh explanations.
- Start against the mock server on day one. The fixtures are already the correct answers, so what you build against mocks is what ships.

### Kashifa — World & Legality (L1/L2)

You own correctness. Everything downstream is wrong if this is wrong.

- **Ship `World` + the loader first** — it unblocks all three of us, so treat it as your day-one deliverable even though it's the least interesting part.
- **Then all 7 LEX rules**, one at a time, each with unit tests, each returning a trace. Read `docs/RULES.md` first: the calendar-day window and the FDP sector reduction are where silent wrong answers come from. Q02 (`20.93h duty / 39.07h headroom`) is your canary — if that's right, your window math is right.
- **Then `JOINT`** — the S6 optimiser. The thing that matters is the **disjointness constraint** (one crew, one pairing); without it you double-book C-3305 and produce an infeasible ₹37,000 plan. Hungarian over a small cost matrix, or exhaustive — both fine. Target: `total_cost_inr: 42500`, and remember 20 different assignments hit it.
- Cost model is a lookup table off `costs.json`. Keep it dumb and data-driven.

### Gayathri — Reasoning & Evals (L2)

- **Start with the eval harness** — it's completely self-contained, you can build it before anyone else's code exists, and it's how the whole team knows where we stand. Load `questions.json` + `scenarios.json`, run each through the API, compare structured answers, print per-tier accuracy. Wire it into CI.
- **Then `RIPPLE`** — the cascade. Start from Q17 (`day2_also_at_risk`, `passengers_day1: 486`); that answer key tells you exactly what a correct cascade produces. Work outward from there.
- **Then `SANDBOX`** — fork the world, apply the perturbation, diff. The four event types are all in `scenarios.json` with worked answers, so you always have a target to hit.
- Every module you write has a scenario that scores it. Use them as your spec — don't invent behaviour the answer keys don't ask for.

### Shared
- **Demo script, slides and backup video** — Shashank + Kiran, during the freeze window.
- **Nobody merges to `main` without the eval score not going down.** CI enforces it.

---

## 9. Working agreement

### Branching
- `main` is **always demoable.** If it's broken, that's the top priority for whoever broke it.
- Branch as `feat/<owner>/<slug>` — e.g. `feat/kashifa/lex-duty-02`.
- Small PRs, squash merge, one quick review. Don't sit on a branch for six hours.
- **T+19 = integration freeze.** No new features. One designated integrator. Bug fixes only.

### The contract is frozen first
`docs/API_CONTRACT.md` plus JSON fixtures are written **before implementation**, and the fixtures are lifted straight from the answer keys — **so the mocks are already the correct answers.**

```
  contract frozen ──┬─► Kiran    builds against mock server     ─┐
                    ├─► Shashank builds agent against fixtures  ─┼─► swap
                    ├─► Kashifa  builds LEX behind it           ─┤   mocks→real
                    └─► Gayathri harness scores both identically─┘
```

Nobody waits on anybody, and the swap from mock to real is a no-op because both sides satisfy the same schema tests. This is the highest-leverage decision in the whole plan — don't route around it.

### Progress
[`PROGRESS.md`](PROGRESS.md) is the live board. Task state auto-syncs from GitHub Issues; the **status pulse** you write by hand every four hours. Two lines each. It takes a minute and it's how we catch a blocker before it costs six hours.

### Scope discipline — things we are deliberately NOT building
- **Passenger rebooking.** Pax impact is a RIPPLE *output* (Q17's `passengers_day1: 486`), not a subsystem.
- **Disruption risk prediction.** The dataset README is explicit: *"provided input — teams do NOT build prediction."* Consume `risk_signals.json`; don't model it.
- **A database.** See §3①.

---

## 10. Repository layout

```
├── README.md                 ← you are here
├── PROGRESS.md               live board + status pulse + eval scorecard
├── DECISIONS.md              one-line ADR log, append-only
├── docs/
│   ├── ARCHITECTURE.md       §4–§7 expanded, with sequence diagrams
│   ├── API_CONTRACT.md       ◄ FROZEN FIRST — the seam everyone codes against
│   ├── RULES.md              all 7 rules → LEX predicate, with the traps
│   ├── AGENT_DESIGN.md       prompts, tool schemas, verifier rules
│   ├── EVAL.md               harness, scorecard, per-tier accuracy
│   ├── SETUP.md              per-role: clone → running in under 10 minutes
│   └── DEMO_SCRIPT.md        the 5-minute run, beat by beat
├── core/                     loader · world · duty · lex · cost · candidates
│                             judge · ripple · sandbox · joint
├── api/                      flask app · routes · sse · schemas
├── agent/                    router · planner · tools · verifier · prompts/
├── frontend/                 angular workspace
├── evals/                    harness.py · scorecard.md · contract_test.py
├── crew-ops-advisor-dataset/ vendored, unmodified — never edit
└── infra/                    Makefile · docker-compose.yml (optional)
```

---

## 11. Stack

Deliberately boring. Every box earns its place at 150 crew and 147 flights.

| Layer | Choice | Why not the bigger thing |
|---|---|---|
| Core | Python 3.12, dataclasses, in-memory `World` | Postgres/Neo4j/Mongo buy nothing under 1 MB |
| Graph | plain dict adjacency | Cypher setup costs more than the traversal it replaces |
| API | Flask + SSE | SSE is all the streaming we need |
| Async | none on the critical path | every op is sub-second in memory; Celery is pure overhead |
| Agent | Claude tool-use | Sonnet 5 for the loop, Haiku 4.5 for the router |
| Retrieval | pgvector on the audit-log Postgres | no second datastore; joins against the decision log |
| UI | Angular + RxJS | RxJS is ideal for the streaming trace |
| Tests | pytest + the 38 gold questions | **the answer keys are the test suite** |

### 11.1 Agent topology — one agent with tools, not a multi-agent system

```
  query
    │
    ▼
  ROUTER      Haiku 4.5 · tier + intent · regex entity extraction
    │
    ▼
  ADVISOR     Sonnet 5 · ONE tool loop, parallel tool calls
    │         lookup · check_legality · find_options
    │         ripple · simulate · joint_plan · explain_rule
    ▼
  VERIFIER    deterministic — set membership over the trace, no LLM
    │
    ▼
  EXPLAINER   Sonnet 5 · typed answer object → controller prose
```

**Why not multi-agent.** All the hard reasoning is already deterministic Python — LEX, RIPPLE, JUDGE, JOINT. A multi-agent decomposition would have language models conferring about work that `core/` computes exactly and instantly, paying serial round-trips for zero added correctness, on a desk whose entire value proposition is speed at 05:00.

Multi-agent earns its place when subtasks need genuinely different context that won't co-exist in one window, or when fan-out over a large noisy search space needs isolated reasoning. Our whole world is 700 KB and every candidate is scored by a pure function. Neither condition holds.

> **Say this to the judges.** *"We evaluated a multi-agent decomposition and rejected it — the reasoning is deterministic, so agent-to-agent chatter adds latency and failure modes without adding correctness."* A defended negative decision is architecture. A cargo-culted swarm diagram is not.
>
> And name it honestly: the above is a **pipeline with three model calls**, not a multi-agent system. Don't put "multi-agent" on the slide.

### 11.2 Retrieval — regex for entities, dense for intent

The whole corpus is **776 tokens** (38 gold prompts) plus ~120 (7 rule texts). That is smaller than one retrieval round-trip, so the router's exemplars go in the **cached system prompt** — it sees all 38 rather than a top-3 approximation. Strictly more accurate, zero infrastructure.

Where retrieval *does* apply — `explain_rule`, and precedent recall over the decision audit log as it grows:

```
  "can C-1042 cover P-2291 on the 15th?"
        ├─► REGEX  → C-1042, P-2291, 2026-09-15    exact, no ranking
        └─► DENSE  → CHECK_LEGALITY, tier 2         k=3, cosine, IDs masked
```

**No BM25.** It is a statistical approximation of exact matching, and we have exact identifiers with known formats (`C-\d{4}`, `P-\d{4}`, `DX\d{3}`, `RULE-[A-Z]+-\d{2}`, dates, 3-letter stations). Regex beats it outright and never mis-ranks. BM25's other job — topical matching — is near-useless on a corpus where all 38 documents share the same vocabulary ("captain", "pairing", "sick", "reserve"). If we ever *do* fuse two rankers, use **Reciprocal Rank Fusion**, not weighted score blending: BM25 scores and cosine similarities live on different scales, so a fixed 0.5/0.5 on raw scores is arbitrary.

**No reranker.** A cross-encoder over 38 candidates costs more latency than the retrieval it corrects. Revisit when the audit log reaches the thousands.

**Two details that matter:**
- **Mask IDs before embedding** — `"Captain C-1042 calls in sick"` → `"Captain <CREW> calls in sick"`. Collapses Q17 and S1 onto the same template, which is exactly what you want when the question is *"what kind of ask is this?"* Biggest single accuracy win available.
- **Abstain below ~0.5 similarity.** Pass no exemplar rather than a misleading one — a bad exemplar steers the planner into the wrong toolchain confidently.

---

## 12. How we prove it works

```bash
python3 crew-ops-advisor-dataset/validate.py   # vendored data intact
pytest core/                                   # one test class per rule ID
python evals/harness.py                        # ← the number we report
```

`harness.py` runs all 38 questions and 6 scenarios through the live agent and prints per-tier accuracy. It runs in CI on every push, and the scorecard in [`PROGRESS.md`](PROGRESS.md) updates itself. **We always know exactly where we stand, and we put that number on the slide.**

The two held-out scenarios in `crew-ops-advisor-dataset/internal/` are **locked**. We run them once, at the end, as an honest self-check — never tuned against. A 96% we can defend beats a 100% we can't.

---

## 13. What we say to the judges

1. **Zero-hallucination by construction.** The LLM cannot compute; a verifier gate rejects unsourced claims. Every answer traces to a data row and a rule ID.
2. **We show the funnel.** 150 → 32 → 21 → 12 → 6, with the reason for every single drop.
3. **RIPPLE.** We model consequence, not lookup — we catch the orphaned day-2 pairing that leg-level thinking misses.
4. **The answer isn't always a person.** *"Deadhead C-2210 from DEL: ₹41,200, three hours late, zero cancellations — versus ₹250,000 to cancel."*
5. **We solve S6 jointly**, under a disjointness constraint — and we recognise that 20 assignments are equally optimal, so we score on cost and feasibility rather than on identity.
6. **The controller keeps the wheel.** Policy sliders, live re-ranking, transparent tradeoffs. Advisor, not autopilot.
7. **We measured it.** Per-tier accuracy against dCortex's own questions and scenarios, in CI, printed on the README. A number, not a claim.

---

## 14. Getting started

**Full instructions for macOS and Windows: [`docs/SETUP.md`](docs/SETUP.md).**
The short version:

```bash
git clone https://github.com/shashank-sk17/dcortex-crew-advisor.git
cd dcortex-crew-advisor
git checkout feat/shashank/dev-console

python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt

python crew-ops-advisor-dataset/validate.py          # prints PASS
pytest -q                                            # 334 passing
```

Then put the database URL in `.env` (ask Shashank — it is not in the repo) and
start the console:

```bash
AGENT_DATA=core AGENT_LLM=anthropic python -m devui.server   # localhost:8420
```

### Read next

| | |
|---|---|
| [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md) | **Start here.** What the system does, the five stages, the traps in the data, and what the model is actually for. |
| [`docs/SETUP.md`](docs/SETUP.md) | macOS and Windows setup, backends, troubleshooting |
| [`docs/FRONTEND.md`](docs/FRONTEND.md) | **integration guide for the UI** — response shapes, what to render, and the question-vs-answer trap |
| [`agent/README.md`](agent/README.md) | the advisor layer in detail |
| [`docs/RULES.md`](docs/RULES.md) | the seven rules and the two conventions that cause silent wrong answers |
| [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) | if you are building against the API |

Then your own section in §8. Put your first status pulse in
[`PROGRESS.md`](PROGRESS.md) when you start.
