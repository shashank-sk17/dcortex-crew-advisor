# Deck Spec — dCortex Crew Ops Advisor

**Slide-by-slide content doc.** Pair with [`DECK_DESIGN_SYSTEM.md`](DECK_DESIGN_SYSTEM.md) — that
file holds every token, layout slot and component recipe referenced below by name (`L-B`, `statement`,
`--near`, etc.). Feed both to Claude Design.

**Canvas:** 1920 × 1080. **Deliverable:** problem statement §5.7 and §8 — *"Presentation deck and live demo."*

---

## 0. How this deck is designed

The brief scores presentation at 10%, but the deck is the *only* artefact the judges read for the
other 55% of the technical rubric. So the running order is the scoring sheet, in weight order,
with the demo cut into the middle where attention is highest.

| Problem statement §7 criterion | Weight | Slides that carry it |
|---|---|---|
| AI Utilization | **20%** | 4, 5, 6, 7, 17 |
| Innovation & Problem Solving | **15%** | 3, 8, 11, 15 |
| Technical Excellence | **15%** | 6, 10, 15, 17 |
| Functionality | **15%** | 9, 10, 13, 16 |
| User Experience | **10%** | 12, 13, 14 |
| Presentation | **10%** | the whole deck |
| Business Impact | 5% | 18 |
| Scalability | 5% | 18 |
| Performance | 5% | 18 |

Three scoring principles from §7 are load-bearing and are each given their own slide, not a bullet:

- *"A polished, reliable Tier 1 with a credible Tier 2 beats a broken Tier 3"* → slide 16
- *"Correctness outweighs coverage"* → slide 15 (green interstitial)
- *"Explainability is weighted throughout, not scored in isolation"* → slides 9, 10, 12 — three
  consecutive slides of visible reasoning, all of them real screenshots

### Running orders

| | Slides | Deck time | Demo | Total |
|---|---|---|---|---|
| **10-minute** | 1,2,4,5,6,7,8,9,11,13,14,16,18,20 | ~5:30 | 4:00 | ~9:30 |
| **15-minute** | all 20 | ~8:30 | 5:00 | ~13:30 + Q&A |

Slides marked **[CUT]** are the ones that drop in the 10-minute order.

### Two rules for whoever builds this

1. **`⟨FILL⟩` is a hard token.** Every one is a number nobody has measured yet. The deck does not
   ship with a guess in any of them. `evals/harness.py` produces them; §7 of the brief says
   *"overstating capability scores badly."* An empty cell we name is worth more than a number we invent.
2. **`⟨C1⟩ … ⟨C9⟩` are screenshot slots.** Capture spec and layout slots in
   `DECK_DESIGN_SYSTEM.md` §8. Take the captures **before** building slides.

---

## Slide 1 — Cover

**Ground:** Night · **Layout:** free · **Time:** 0:15 · **[KEEP]**

- **Eyebrow** `x112 y96`: `DCORTEX · AGENTIC CREW OPS ADVISOR`
- **Live pill** (§7.7) below the eyebrow: `● S1–S6 SEEDED · LIVE DEMO`
- **`display`** (124px/900), bone, `x112`, baseline block `y 520…780`:
  > Crew Control,
- **`display` italic green** on the next line:
  > *at 6 a.m.*
- **`body`** at `y 900`, `rgba(247,245,241,0.62)`, 46ch:
  > A conversational advisor for the crew-control desk. Legally verified. Cost ranked. Every number cited.
- **Footer row** `y 984`, `micro`, `rgba(247,245,241,0.62)`: `TEAM ⟨FILL: team name⟩ · SHASHANK · KIRAN · KASHIFA · GAYATHRI`

*Optional background:* night-ops imagery under the two hero overlays (design system §12). If there is
no image that is genuinely good, use flat `--dark`. A flat cover beats a bad photo.

---

## Slide 2 — The moment

**Ground:** Night · **Layout:** free · **Time:** 0:40 · **[KEEP]**

- **Eyebrow:** `THE PROBLEM`
- **`statement`**: `05:00. A captain calls in sick.`
- Four **`body`** lines, hairline-separated, revealing on a 60ms stagger, each `rgba(247,245,241,0.72)`,
  with a leading **Mono** timestamp in `--green`:

| | |
|---|---|
| `+0m` | Three legs of pairing **P-2291** are now uncrewed. |
| `+2m` | The pairing overnights at DEL — day 2 is orphaned too. |
| `+5m` | Six screens: roster, duty clocks, reserve register, certifications, cost card, the rulebook. |
| `+20m` | An answer. The aircraft has been on stand for twenty minutes. |

- **Closing `lead`** at the foot, bone:
  > This is one disruption. A bad morning brings four.

**Say:** the brief's own opening — every airline runs on a plan, and the day never works perfectly.
Don't read the slide.

---

## Slide 3 — The bottleneck is not detection

**Ground:** Night · **Layout:** free · **Time:** 0:25 · **[CUT]**

- **Eyebrow:** `WHAT IS ACTUALLY HARD`
- **`statement` + italic turn** (§7.2):
  > Detecting that something broke is easy.
  > *Reasoning correctly about what breaks next is not.*
- Five **feature items** (§7.3) in a `repeat(5,1fr)` grid with a top hairline — verbatim from the
  brief's pain points:

| Green bar + title | Body |
|---|---|
| Fragmented data | One answer spans rosters, duty clocks, schedules, reserve registers, qualifications and the rulebook. |
| Consequence blindness | The broken flight is obvious. The four that break next are not. |
| Legality is exact arithmetic | An approximate answer is a violation. |
| Expertise bottleneck | Only senior controllers can do this fluently — one disruption at a time. |
| No reasoning trail | Decisions can't be reviewed, trusted or learned from. |

**Say:** "The brief names five pain points. Four of them are solved by retrieval. The third one —
*legality is exact arithmetic* — is the one that decides your architecture."

---

## Slide 4 — The question the brief actually asks

**Ground:** **GREEN** `#7ed321` · **Layout:** centred · **Time:** 0:25 · **[KEEP]**

Full-bleed green. `--dark` ink. No eyebrow, no logo, nothing else on the slide.

- **`quote` scaled to 64px/800/-0.025em**, centred, max 30ch measure:
  > What should the language model do, what should deterministic code do, and how do you compose
  > them into a system that is both conversational and correct?
- **`micro`** beneath, `rgba(7,9,11,0.55)`: `PROBLEM STATEMENT §2 — THE CENTRAL ENGINEERING CHALLENGE`

**Say:** "We're going to answer this one question, and everything else in the deck falls out of it."
Then pause. This is the deck's hinge.

---

## Slide 5 — Our answer

**Ground:** Night · **Layout:** free · **Time:** 0:35 · **[KEEP]**

- **Eyebrow:** `THE ONE DECISION EVERYTHING HANGS ON`
- **`statement` + italic turn** — the signature moment of the deck:
  > The model selects, sequences and narrates.
  > *It never calculates.*
- Below, two columns split by a vertical hairline at centre, each with an `eyebrow`-scale label:

| `ABOVE THE TOOL LINE` | `BELOW THE TOOL LINE` |
|---|---|
| Understand the question. Choose the tools. Explain the evidence in the controller's language. | Pure Python. Every number, name, verdict and rule citation. Unit-tested against dCortex's own answer keys. |
| *Flexible* | *Zero hallucination surface* |

- **Footer `body`**, `--green`:
  > A verifier gate rejects any claim not traceable to a tool output. Zero-hallucination is a
  > structural property here, not a hope.

---

## Slide 6 — Architecture

**Ground:** Night · **Layout:** free, full-bleed diagram · **Time:** 0:50 · **[KEEP]**

> **Mandatory deliverable** — problem statement §5.4 and §8: *"Architecture diagram — including the
> LLM vs. deterministic boundary."* This slide must survive being screenshotted on its own.

- **Eyebrow:** `ARCHITECTURE`
- **`sub`** (56px): `Four layers. One boundary that matters.`
- **Diagram**, drawn as vector (not a screenshot of ASCII), `x112 y280 w1696 h680`:

```
L4  OPS CONSOLE            Angular 19 · RxJS · SSE
    board · crew · alerts · conversation + evidence rail
                    ── HTTP/JSON + SSE · frozen contract ──
L3  ADVISOR AGENT          Claude
    ROUTER → PLANNER → TOOL LOOP → VERIFIER → EXPLAINER
    Haiku 4.5   Sonnet 5    parallel    deterministic   Sonnet 5

  ═══════════  THE TRUST BOUNDARY — the tool interface  ═══════════

L2  REASONING CORE         deterministic · unit-tested
    LEX · RIPPLE · JUDGE · SANDBOX · JOINT
L1  OPS-GRAPH              in-memory typed world
    crew · qual · cert · duty-clock · pairing · leg · aircraft · station
    12 JSON files · immutable base · copy-on-write forks
```

**Drawing rules:**
- The trust boundary is the only **2px `--green`** rule on the slide, spanning the full 1696px, with
  its label set in `--green` `micro` centred **on** the line. Every other divider is a 1px hairline.
- L4/L3 sit in bone-at-0.72 ink. **L2/L1 sit inside a `--green` 1px bounding box** — deterministic
  territory is drawn as one enclosed region, because that is the claim.
- Layer names and layer numbers in **Mono**. Prose in Sans.
- No arrows between the five organs. They are peers, not a pipeline.

**Say:** "Above the green line is the only place a language model runs. Everything below it is
Python you can unit-test. That line is why our numbers are trustworthy."

---

## Slide 7 — The Cortex

**Ground:** Night · **Layout:** free · **Time:** 0:40 · **[KEEP]**

- **Eyebrow:** `THE PROPRIETARY MODEL`
- **`statement`:** `Five organs over one graph.`
- **`lead`**, `rgba(247,245,241,0.62)`, 46ch:
  > None of this comes out of an API. We construct all of it.
- Five **feature items** (§7.3), `repeat(5,1fr)`, top hairline. Titles in **Mono** `--green`:

| | |
|---|---|
| `LEX` | Seven rules as individually addressable predicates. Every rule returns a verdict **plus a trace** — never a bare boolean. |
| `RIPPLE` | Depth-limited traversal over the ops-graph. Computes the blast radius of pulling one crew member. |
| `JUDGE` | Legality is a hard gate. Survivors ranked by `(cost_inr, delay_hours)` against a published rate card. |
| `SANDBOX` | Copy-on-write world fork → apply the perturbation → re-run LEX and RIPPLE → diff the two worlds. |
| `JOINT` | Simultaneous disruptions as one problem, under a hard disjointness constraint. |

- **Footer `body`** `--green`: `Crew fly pairings, not legs. Encoding that as structure is what catches the day-2 failure.`

---

## Slide 8 — RIPPLE

**Ground:** Night · **Layout:** **L-B split** · **Screenshot:** `⟨C4⟩ 08-blast-radius@2x.png` · **Time:** 0:45 · **[KEEP]**

- **Eyebrow:** `INNOVATION · CONSEQUENCE, NOT LOOKUP`
- **`sub`** (56px, left column, w672):
  > Pull one captain and seven things move.
- Left column, **Mono `data-sm`** cascade list, each row with a `--near` tag on the right:

```
CPT C-1042 sick · pairing P-2291
  DX412 / DX413 / DX588 · 15 Sep uncrewed        DIRECT
  486 passengers affected, day 1                 PAX
  DX589 / DX590 / DX591 · 16 Sep at risk —
    the pairing overnights at DEL                ORPHANED DAY 2
  replacement pulled off their own duty          2ND ORDER
  DEL cover needs a DX402 deadhead               POSITIONING
  BLR reserve depth 4 → 3                        POOL
  VT-DXA rotation slips ~3h                      AIRCRAFT
```

- **Right:** `⟨C4⟩` in the L-B screen slot, bleeding off the right edge.
- **Footer `body`**, bone:
  > Leg-level thinking misses the orphaned day 2. That is the failure most systems ship.

---

## Slide 9 — The funnel

**Ground:** Night · **Layout:** **L-D detail** · **Screenshot:** `⟨C2⟩ 09-funnel@2x.png` · **Time:** 0:40 · **[KEEP]**

- **Eyebrow:** `EXPLAINABILITY · 1 OF 3`
- **`statement` + italic turn:**
  > 150 crew in. Six out.
  > *Every single drop is inspectable.*
- **Left:** `⟨C2⟩` full console at `x112 y300 w1100`, with a **green box** (§8.4) around the funnel component.
- **Right inset:** the magnified funnel crop at `x1120 y380 w688 h480`, label `micro --green`: `AS RENDERED IN THE CONSOLE`
- Overlay the inset's numbers as **Mono** if the capture is low-contrast; otherwise leave the
  screenshot untouched:

```
150  all crew
 ─ 118  not Captain                            ROLE
 32  captains
 ─  11  no A320 rating / leave / training      QUAL-05
 21  qualified & active
 ─   9  duty conflict — already rostered       AVAIL
 12  free
 ─   6  rule breach — full trace attached      LEX
  6  LEGAL   + 2 NEAR-MISS
```

**Say:** "Trust is inspectability. A controller believes what they can audit — so we render the audit."

---

## Slide 10 — The legality trace

**Ground:** Night · **Layout:** **L-D detail** · **Screenshot:** `⟨C3⟩ 10-rule-trace@2x.png` · **Time:** 0:45 · **[KEEP]**

- **Eyebrow:** `EXPLAINABILITY · 2 OF 3`
- **`statement` + italic turn:**
  > Seven rules. Seven verdicts.
  > *Never a bare boolean.*
- **Left:** `⟨C3⟩` with a green box around the failing rule row.
- **Right inset:** the crop, plus the trace typeset in **Mono `data-sm`** with the §3.2 legend inks —
  every verdict as `ink + text token + glyph`:

```
RULE-FDP-01   max FDP              ✓ PASS   11h15m used / 12h00m limit (4 sectors)
RULE-DUTY-02  60h / 7 cal-days     ✗ FAIL   61.33h — exceeds by 1h20m on 2026-09-15
RULE-FLT-03   100h / 28 days       ✓ PASS   64.27h / 100h
RULE-REST-04  min 12h rest         ✓ PASS   14h20m since last release
RULE-QUAL-05  type rating          ✓ PASS   A320 valid
RULE-CERT-06  certifications       ✓ PASS   all 4 valid on duty date
RULE-BASE-07  base / deadhead      ✓ PASS   BLR own-base reserve callout
```

- **Footer `body`** `--green`:
  > Rules are data, not code branches. Every FAIL is quotable to the controller and to an auditor.

> **Guard:** these seven are the entire rulebook. The slide must not imply broader regulatory coverage.

---

## Slide 11 — The answer isn't always a person

**Ground:** Night · **Layout:** **L-B split** · **Screenshot:** `⟨C5⟩ 11-options-card@2x.png` · **Time:** 0:45 · **[KEEP]**

- **Eyebrow:** `INNOVATION · THE ACTION SPACE`
- **`sub`:** `The action space is wider than "pick a crew member."`
- Left column, **Mono `data-sm`** ranked list — rank 1 distinguished by position and a hairline only,
  **never a badge or crown** (guard §10.1):

```
#1  C-3310  reserve callout, BLR         ₹18,500   +0.0h   blast 0
#2  C-1526  day-off callout              ₹24,000   +0.0h   blast 0
#3  C-2210  deadhead DEL→BLR on DX402    ₹41,200   +3.0h   blast 2
✗   C-2087  RULE-DUTY-02  +1h20m (61.33h vs 60h)
```

- Beneath it, the near-miss framed as a **`quote` at 32px** with a 2px `--green` left rule:
  > No captain is legal at 06:00. But C-2210 out of DEL becomes legal via the DX402 deadhead —
  > ₹41,200 all-in, DX412 departs ~3h late, zero cancellations. Versus **₹250,000** to cancel one leg.
- `₹41,200` in `--near`, `₹250,000` in `--breach`. Both **Mono**.
- **Right:** `⟨C5⟩`, bleeding right.
- **Footer `body`:** `Delay · deadhead · pairing swap · re-crew the tail legs · cancel. All in the action space, with the cost contrast made explicit.`

---

## Slide 12 — The controller keeps the wheel

**Ground:** Night · **Layout:** **L-C triptych** · **Screenshots:** `⟨C7⟩ ⟨C8⟩ ⟨C9⟩` · **Time:** 0:35 · **[CUT]**

- **Eyebrow:** `EXPLAINABILITY · 3 OF 3 · USER EXPERIENCE`
- **`sub`:** `Advisor, not autopilot.`
- Three component crops, 512×384 each, captions in `micro --green` below:

| Slot | Capture | Caption |
|---|---|---|
| 1 | `⟨C7⟩ trace-panel` | `LIVE TOOL-CALL TRACE — WHAT IT ASKED, IN ORDER` |
| 2 | `⟨C8⟩ crew-drawer` | `DUTY CLOCK, EXPIRING CERTS, PER-PAIRING LEGALITY` |
| 3 | `⟨C9⟩ policy-sliders` | `MOVE A WEIGHT — THE RANKING REORDERS, WITH FRESH REASONING` |

- **Footer `body`**, bone:
  > It advises and ranks. The human decides. v1 records the decision — it never mutates a roster.

---

## Slide 13 — The console

**Ground:** Night · **Layout:** **L-E whole** · **Screenshot:** `⟨C1⟩ 13-console-board@2x.png` · **Time:** 0:20 → **DEMO** · **[KEEP]**

One screenshot, uncropped, 1536×864. Nothing competing with it.

- **Eyebrow** in the baseline row: `LIVE DEMO`
- **Caption**, right-aligned, `rgba(247,245,241,0.62)`:
  > Flights board · alert queue · crew view · advisor. One console.

**This slide is the handoff to the live demo.** Say one sentence and switch to the app.

### Demo beats — 4:00 / 5:00

| # | Beat | Shows | Rubric |
|---|---|---|---|
| 1 | Tier 1: *"Who's on reserve at BLR tomorrow?"* | it is fast and it is right | Functionality |
| 2 | Tier 2 / **S2**: *"Captain C-1042 just called in sick for P-2291"* | funnel + 7-rule trace stream in live | AI Utilization, Explainability |
| 3 | The orphaned day 2 appears in the blast radius | consequence, not lookup | Innovation |
| 4 | Tier 3: ranked options — surface the ₹41,200 deadhead near-miss | the answer isn't always a person | Innovation, Business Impact |
| 5 | Move a policy weight, ranking reorders | the controller keeps the wheel | UX |
| 6 | Ask something out of scope → the abstain card | honest limits | §7 scoring principles |
| 7 | Record the decision | audit trail, no roster mutation | UX |

**Backup video is banked at T+21.** If the live app fails, cut to it without commentary and keep talking.

---

## Slide 14 — When it isn't sure

**Ground:** Night · **Layout:** **L-B split** · **Screenshot:** `⟨C6⟩ 14-abstain-card@2x.png` · **Time:** 0:35 · **[KEEP]**

> **Mandatory deliverable** — §5.6: *"at least one case your system handles poorly, with your analysis."*
> §7: *"Honest failure analysis scores well."*

- **Eyebrow:** `THE HONEST PART`
- **`sub` + italic turn:**
  > A confident wrong answer is worse than no answer.
  > *So we built saying so as a surface.*
- Left column, three items with green bars:

| | |
|---|---|
| **What it refuses** | ⟨FILL: the specific class of question the abstain path catches — from `evals/harness.py` output⟩ |
| **The case we handle poorly** | ⟨FILL: one named failure, with the reason. Not a hypothetical — a real one from the eval run.⟩ |
| **What it would need** | ⟨FILL: the missing input or tool that would make it answerable⟩ |

- **Right:** `⟨C6⟩` — the abstain card as it actually renders.
- **Footer `body`** `--near`:
  > "I can't answer that reliably" — plus what it would need — is a first-class output, not an error state.

> ⚠️ **Do not build this slide from imagination.** Run the harness, pick the real failure, write the
> real analysis. This is the slide that earns the most credit for the least engineering, and the
> fastest to lose it on if the failure is fictional.

---

## Slide 15 — Correctness over coverage

**Ground:** **GREEN** `#7ed321` · **Layout:** centred · **Time:** 0:15 · **[CUT]**

Full-bleed green, `--dark` ink, nothing else.

- **72px/800/-0.025em**, centred:
  > Ten right and one honest
  > beats eleven with three wrong.
- **`micro`**, `rgba(7,9,11,0.55)`: `PROBLEM STATEMENT §7 — SCORING PRINCIPLES`

---

## Slide 16 — How we prove it works

**Ground:** **Bone** `#f7f5f1` · **Layout:** free · **Time:** 0:45 · **[KEEP]**

The deck steps into the light exactly once, to show its work. Ink `--text`, eyebrow `--green-ink`,
hairlines `--border`.

- **Eyebrow:** `FUNCTIONALITY · MEASURED, NOT CLAIMED`
- **`statement`:** `The answer keys are the test suite.`
- **Scorecard**, hairline table (§7.8), **Mono**, centred at `y 400`:

| Tier | What it tests | Questions | Passing | % |
|---|---|---|---|---|
| 1 — Lookup | Retrieve a fact | 16 | ⟨FILL⟩ | ⟨FILL⟩ |
| 2 — Consequence | Impact and cascade | 14 | ⟨FILL⟩ | ⟨FILL⟩ |
| 3 — Recommendation | Rank legal options | 8 | ⟨FILL⟩ | ⟨FILL⟩ |
| Scenarios | S1–S6 end to end | 6 | ⟨FILL⟩ | ⟨FILL⟩ |
| **Total** | | **44** | **⟨FILL⟩** | **⟨FILL⟩** |

Passing cells in `--green-ink`. Any tier below target in `--near-ink` — **shown, not hidden.**

- Three **feature items** beneath, `repeat(3,1fr)`:

| | |
|---|---|
| Runs in CI | `python evals/harness.py` on every push. The scorecard updates itself. |
| Held-out set, locked | Two scenarios we have never run. Opened once at T+21 as an honest self-check. Result: ⟨FILL⟩ |
| Never tuned against | A defensible ⟨FILL⟩% beats an unexplainable 100%. |

---

## Slide 17 — What we decided not to build

**Ground:** Bone · **Layout:** free · **Time:** 0:35 · **[CUT]**

- **Eyebrow:** `TECHNICAL EXCELLENCE · DEFENDED NEGATIVES`
- **`statement` + italic turn** (`--green-ink`):
  > Every box has to earn its place.
  > *Five didn't.*
- Hairline-separated rows, title `card-title`, reason `card-body` `--muted`:

| Not built | Why |
|---|---|
| **No database** | The world is < 700 KB. Postgres, Neo4j or Mongo cost a day in schema and Docker and buy nothing at 150 crew and 147 flights. |
| **No multi-agent system** | All the hard reasoning is already deterministic Python. Agents conferring about work `core/` computes exactly adds latency and failure modes, not correctness. This is a pipeline with three model calls, and we call it that. |
| **No BM25** | We have exact identifiers with known formats. Regex beats a statistical approximation of exact matching, and never mis-ranks. |
| **No reranker** | A cross-encoder over 38 candidates costs more latency than the retrieval it corrects. |
| **No trained ranker** | Ranking is provably optimal against the published rate card. We log every accept/reject as a preference pair so weights *can* be learned once real usage exists. Claiming a model we don't have is the fastest way to lose the room. |

- **Footer `body`** `--green-ink`: `A defended negative decision is architecture. A cargo-culted swarm diagram is not.`

---

## Slide 18 — What it's worth

**Ground:** Bone · **Layout:** stat cards + feature row · **Time:** 0:35 · **[KEEP]**

- **Eyebrow:** `BUSINESS IMPACT · SCALABILITY · PERFORMANCE`
- **`statement`:** `Twenty minutes of cross-referencing, or one question.`
- Two **stat cards** (§7.4), `1fr 1fr`, both on `--dark` ground inverted onto the bone slide:

| Card | Label | Numeral | Desc |
|---|---|---|---|
| Left | `TODAY` (`--breach`) | `~20` `min` | Six screens: rosters, duty clocks, reserve register, certifications, cost card, rulebook. |
| Right | `WITH THE ADVISOR` (`--green`) | `⟨FILL⟩` `s` | One question. Ranked, legally verified, cited. Measured p50 over the 38 gold questions. |

> ⚠️ **Honesty guard.** The `~20 min` figure is the manual workflow described in the brief and in
> `PRODUCT.md`. The right-hand number must be **our measured latency**, not dCortex's published
> customer outcome. Do not borrow a real result from dcortex.ai and present it as ours.

- Three **feature items** beneath:

| | |
|---|---|
| **Performance** | The brief's bar: *"a 45-second response is not a decision aid."* Ours: ⟨FILL⟩s p50, ⟨FILL⟩s p95. |
| **Scalability** | Every organ is a pure function over an indexed graph. At real carrier scale the funnel is a partitioned scan; LEX is per-candidate and embarrassingly parallel. The in-memory `World` is the part that would be swapped, and it sits behind one interface. |
| **Business impact** | Legality checked exactly rather than approximately. One prevented cancellation is ₹250,000 against a ₹18,500 reserve callout. |

---

## Slide 19 — Limits

**Ground:** **Trust band** `#0d1008` · **Layout:** free · **Time:** 0:25 · **[CUT]**

- **Eyebrow:** `WHAT THIS IS NOT`
- **`sub`:** `Stated plainly, because the brief asks for it.`
- Five **trust items** (green bar + title + body), `repeat(5,1fr)`, top hairline:

| | |
|---|---|
| Not a prediction model | Disruption-risk scores are a provided input, shown as-is. We reason about them; we don't produce them. |
| Not a system of record | v1 records a controller's decision. It does not mutate a roster. |
| Seven rules, not a rulebook | `RULE-FDP-01` … `RULE-BASE-07` is the entire regulatory scope, and we say so on every legality surface. |
| Synthetic world | 150 crew, one week, one carrier. Relationally realistic, not statistically calibrated. |
| No production infrastructure | No auth, no multi-tenancy, no integrations. Deliberately — the brief says not to spend hackathon hours there. |

- **Footer `body`**, `rgba(247,245,241,0.62)`:
  > On PII: crew identifiers are the only personal data in scope. In production this system would
  > hold them behind the tool boundary and cite by role and ID, never by name, in any logged trace.

---

## Slide 20 — Close

**Ground:** Night · **Layout:** centred · **Time:** 0:20 · **[KEEP]**

- **`sub`** (56px), bone, centred, max 34ch — the brief's own closing line, attributed:
  > The Advisor a real crew controller would want beside them at 6 a.m. on a bad day —
- Then, `display` scale 88px, three lines, centred, each the italic green treatment on the final word:

  > because it is **fast**,
  > because it is **right**,
  > and because when it isn't sure, *it says so.*

- **`micro`**, `rgba(247,245,241,0.62)`: `PROBLEM STATEMENT — CLOSING LINE`
- **Footer row:** repo URL · team names · `micro`.

**Say nothing over this slide except the last line.** Then stop.

---

# Appendix — held in reserve for Q&A

Built, not presented. Jump to them by number when asked.

| # | Slide | Ground | Content |
|---|---|---|---|
| **A1** | The seven rules | Bone | All 7 rule IDs, constraint text, and the two traps: DUTY-02 / FLT-03 are **calendar-day** windows, not rolling; FDP-01 = `13h − 0.5h × (sectors − 2)`, so 4 sectors caps at 12.0h. |
| **A2** | The rate card | Bone | Mono table: reserve callout pilot ₹18,500 / cabin ₹9,500 · day-off pilot ₹24,000 / cabin ₹12,500 · deadhead +₹6,500 · delay +₹5,400 per duty hour · hotel ₹4,200 · **cancellation ₹250,000 per leg**. |
| **A3** | Dataset profile | Bone | 150 crew · 147 flights · 39 pairings · 16 reserves · 8 stations · 6 aircraft · 7 rules · 38 gold questions · 6 scenarios + 2 held out · **< 700 KB total**. The slide that justifies "no database". |
| **A4** | S6 — joint assignment | Night | Both A320 captains sick at 00:30Z, 18 Sep. Solve independently → C-3305 assigned twice for ₹37,000: **infeasible, not suboptimal.** JOINT enforces disjointness → **₹42,500**. And there are **20 equally optimal answers** — ten captains at ₹24,000, two interchangeable roles — so the harness scores cost + feasibility + distinct IDs, never `crew_id`. |
| **A5** | Retrieval | Night | Corpus is 776 tokens, so all 38 exemplars live in the cached system prompt rather than a top-3 approximation. Regex for entities (`C-\d{4}`, `P-\d{4}`, `DX\d{3}`, `RULE-[A-Z]+-\d{2}`), dense for intent. IDs masked before embedding. Abstain below ~0.5 similarity. |
| **A6** | Team & repo | Bone | Four people, four seams, one frozen contract: Shashank (advisor agent) · Kiran (ops console) · Kashifa (world & legality) · Gayathri (reasoning & evals). Repo, README, `DECISIONS.md`, `docs/API_CONTRACT.md`. |
| **A7** | Sample I/O | Night | One Tier-1, one Tier-2, one Tier-3 question with the **typed answer object** beside the rendered prose — showing prose is always *rendered from* the object, never authored first. Deliverable §5.6. |

---

## Build checklist

- [ ] Take all nine captures `⟨C1⟩…⟨C9⟩` at 1920×1080 DPR 2, seeded scenarios, dark theme, no browser chrome
- [ ] Run `python evals/harness.py` and fill every `⟨FILL⟩` in slides 16 and 18
- [ ] Pick the real failure case for slide 14 from that run — never invent it
- [ ] Measure p50 / p95 latency over the 38 gold questions for slide 18
- [ ] Open the held-out set once, at T+21, and put the number on slide 16 whatever it is
- [ ] Read every slide against the five guards in `DECK_DESIGN_SYSTEM.md` §10
- [ ] Export to PDF and check every slide reads correctly frozen, with no motion
- [ ] Rehearse 3× against a clock; confirm the 10-minute cut still tells a whole story
