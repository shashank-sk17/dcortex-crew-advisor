# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary — airline crew controllers on a live shift.** A small team working the
highest-pressure desk in an airline. The moment the product is built for: a
disruption has just hit — a captain calls in sick at 05:00, a station closes for
six hours, a tech delay cascades down an aircraft rotation, a certificate lapses —
and the controller must, within minutes, work out who is affected, which flights
are now at risk (including downstream legs in the same pairing), which crew can
*legally* be moved, who can actually be reached, and what it costs. Today they do
this by hand, cross-referencing rosters, duty clocks, reserve lists and a dense
regulatory rulebook across several screens while an aircraft sits on stand. The
reasoning currently lives in senior controllers' heads — slow to learn,
impossible to scale, and it degrades exactly when it matters most.

**Secondary — hackathon judges.** The console is also demonstrated live (a ~5-minute
walkthrough) and scored against a rubric (AI utilization, innovation, technical
excellence, functionality, UX, presentation, business impact, scalability,
performance). It must survive that demo, but every design trade-off resolves
toward real desk usability first; presentation impact only breaks ties.

## Product Purpose

A conversational and operational advisor for the crew-control desk. The controller
asks in plain English — *"Captain C-1042 just called in sick for P-2291, who do I
use?"* — and gets a legally-verified, cost-ranked, fully-cited answer in seconds
instead of ~20 minutes of manual cross-referencing.

It answers three tiers of question:
1. **Lookup** — retrieve a fact ("who is on reserve at BLR on 15 Sep?").
2. **Consequence** — reason about impact and cascade ("C-1042 is out for P-2291 —
   which flights are now uncrewed, and what breaks next?").
3. **Recommendation** — rank legal options against real trade-offs, with cost,
   legality status, reachability and reasoning; optionally draft the crew
   notification.

Success: a controller under time pressure trusts it enough to act on it — because
it is fast, because it is right, and because when it isn't sure, it says so.

## Positioning

**The language model selects, sequences and narrates. It never calculates.**

Every number, name, verdict and rule citation in an answer originates from a
deterministic tool call behind a hard trust boundary at the tool interface. Below
the line is pure, tested, reproducible code; above it is the flexible
natural-language layer. A verifier gate rejects any answer containing a claim not
traceable to a tool output — so zero-hallucination is a structural property of the
architecture, not a hope.

What a neighbouring product cannot truthfully copy:
- **Legality is exact arithmetic** against a fixed 7-rule rulebook, returned as a
  verdict *plus a trace* — never a bare boolean.
- **Ranking is provably cost-optimal** against a published rate card, not learned.
- **It is auditable in the UI** — the candidate funnel (150 → role → qualified →
  available → legal, with the reason for every drop), the 7-rule legality trace,
  and the disruption blast radius all render on screen, because trust is
  inspectability.
- **It models consequence, not just lookup** — it catches the orphaned day-2
  pairing that leg-level thinking misses.
- **The answer isn't always a person** — deadhead positioning, a departure delay
  that buys legality, a pairing swap, re-crewing the tail legs, or a cancellation
  are all in the action space, with the cost contrast made explicit.

## Operating Context

- **Synthetic world.** Carrier "dCortex Air", hub BLR, one operating week
  2026-09-14 → 2026-09-20. All times UTC; currency INR. Snapshot "now" is
  2026-09-14T18:00:00Z.
- **Scale.** 150 crew, 147 flights, 8 stations, 6 aircraft (4× A320, 2× ATR72),
  39 pairings, 16 reserves with on-call windows, 4 certification types per crew,
  a fixed cost rate card, and pre-computed per-crew disruption-risk signals.
- **Crew fly pairings, not legs.** A pairing is a multi-day rotation that can
  overnight away from base; replacing a crew member on day 1 can strand day 2.
- **The 7 rules** (the entire rulebook — see Capabilities): FDP-01, DUTY-02,
  FLT-03, REST-04, QUAL-05, CERT-06, BASE-07. Duty and flight-hour windows are
  **calendar-day** based, not rolling. The FDP limit shrinks 0.5h per sector
  beyond the 2nd.
- **Reserves** are usable only when the *required report time* (after any deadhead
  positioning) falls inside their on-call window. Cross-base cover requires a
  deadhead: positioning cost + the delay it forces.
- **Disruption event types** in scope: sick crew, station closure, technical
  delay, certification expiry, and simultaneous / multi-event.
- **Performance bar.** An answer that takes 45 seconds is not a decision aid.
- **Team & build.** Four people — two AI, one backend, one frontend (Angular /
  RxJS) — building in parallel against a frozen contract across four layers:
  in-memory ops-graph, deterministic reasoning core, the advisor agent, and the
  web ops console. Backend is Python / Flask over an in-memory `World`; the agent
  uses Claude (Sonnet 5 for the tool loop, Haiku 4.5 for routing); the console is
  Angular 19.

## Capabilities and Constraints

- **Three question tiers.** Tier 1 is mandatory and must be rock-solid; Tier 2 is
  strongly expected; Tier 3 is a stretch. Correctness outweighs coverage —
  answering ten questions correctly and saying "I can't answer that reliably" on
  the eleventh beats answering all eleven with three wrong.
- **Explainability is mandatory.** Every non-trivial answer carries reasoning the
  controller can read and challenge. A correct answer with no visible reasoning
  scores poorly.
- **Honest uncertainty is a first-class feature.** "I can't answer that reliably"
  plus what it would need, rendered as its own surface — never a confident wrong
  answer.
- **BINDING design guard — advisor, not autopilot.** The controller keeps the
  wheel. The UI must never imply the system decides or acts on its own: no
  "auto-resolve", no agentic self-assignment framing. It advises and ranks; the
  human decides.
- **BINDING design guard — the 7 named rules are the whole rulebook.** Legality UI
  must not imply broader regulatory coverage than FDP-01 … BASE-07.
- **Scope facts** (record, no active UI guard required): disruption-risk scores
  are a provided input shown as-is — there is no prediction model. Passenger
  rebooking is not a feature; passenger impact is an output number only. There is
  no database — the entire world is < 700 KB held in memory, so there is no system
  of record. v1 performs no roster mutation; the intended write path is
  logging / staging a controller's decision (an audit trail and future
  preference-pair data), not committing an assignment.
- **Frontend is a view layer over REST** for all operational data — flights board,
  crew, alerts, sidebar. The conversational advisor is a separate streaming (SSE)
  channel confined to a chat surface.
- **Terminology.** pairing; duty period; FDP (flight duty period); sector; report
  / release; on-call window; deadhead / positioning; reserve callout vs day-off
  callout; blast radius; near-miss; the candidate funnel; and the five reasoning
  organs — LEX (legality), RIPPLE (cascade), JUDGE (cost ranking), SANDBOX
  (counterfactual), JOINT (multi-event assignment).
- **The vendored dataset is immutable** — never edited; `validate.py` is the
  canary that it stayed intact.

## Brand Commitments

- **Name.** "dCortex" is the company hosting the exercise (fictional for the
  hackathon). The product is the **Crew Ops Advisor** (a.k.a. Agentic Crew Ops
  Advisor). The synthetic carrier is "dCortex Air".
- **No established visual identity, logo, or brand voice for the console yet** —
  deliberately open; a visual world is chosen in later design work, not here.
- **Guiding line from the brief** (not a tagline to display, a north star):
  *the Advisor a real crew controller would want beside them at 6 a.m. on a bad
  day — because it is fast, because it is right, and because when it isn't sure,
  it says so.*

## Evidence on Hand

- `crew-ops-advisor-dataset/` — vendored synthetic dataset: 12 JSON files (crew,
  flights, rosters, duty_clocks, reserve_pool, certifications, rules, costs,
  risk_signals, scenarios) plus `validate.py` and `generate.py`.
- `crew-ops-advisor-dataset/data/questions.json` — 38 gold questions with expected
  answers (16 Tier-1, 14 Tier-2, 8 Tier-3).
- `crew-ops-advisor-dataset/data/scenarios.json` — 6 worked disruption scenarios
  (S1–S6) with computed answer keys; 2 further scenarios held out and locked in
  `internal/`.
- `docs/` — `API_CONTRACT.md`, `RULES.md`, `SETUP.md`, plus this build's
  `CONTRACT_RECONCILIATION.md` and `REST_API_v1.md`.
- `README.md`, `DECISIONS.md` (append-only ADR log), `PROGRESS.md` (live board).
- The problem statement PDF (`problem_explanation_k66g3nx88t.pdf`) — held by the
  team, not committed to the repo.
- `frontend/` — a working Angular 19 cockpit whose data is served today by an
  in-app mock computed from the bundled dataset; builds clean.
- **Absences future work must not fabricate:** no real airline data; no live
  weather / METAR feed; no passenger-level records (only aggregate seat counts);
  no production infrastructure, authentication, or real system integrations; no
  trained ranking model.

## Product Principles

1. **Deterministic below the tool line, natural language above it.** The model
   chooses tools and explains evidence; it never computes. Every number traces to
   a data row and a rule ID.
2. **Trust is inspectability.** Show the funnel, the 7-rule trace, the blast
   radius. An answer a controller cannot audit is worthless.
3. **Correctness over coverage.** A rock-solid Tier 1 with a credible Tier 2 beats
   a broken Tier 3. When unsure, say so.
4. **The controller keeps the wheel.** Advise and rank; never decide or act.
   Trade-offs are transparent and adjustable.
5. **Built for the 6 a.m. bad day.** Fast enough for a live shift, legible under
   pressure, honest about its limits.

## Accessibility & Inclusion

No product-specific standard was established. Operating context to carry forward:
a high-pressure control desk, plausibly a dark / night-shift environment,
sustained screen use, and decisions made against a countdown. This favours high
legibility, status encoded by more than colour alone, and low cognitive load —
recorded as context, not a mandated standard.
