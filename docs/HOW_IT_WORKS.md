# How it works

Read this before changing anything. It explains what the system does, the one
decision everything else follows from, and where the bodies are buried.

Setup is [`SETUP.md`](SETUP.md).

---

## 1. What it does

A crew controller asks a question in plain English and gets a legally-verified,
cost-ranked, fully-cited answer.

> **"Captain of P-2291 is not available on 2026-09-15"**
>
> ```
> ▸ Assign Captain C-3310 (reserve callout) — ₹18,500, no delay
>   Clears all 7 rules.
>
> Alternatives:
>   #2 Assign Captain C-1526 (day-off callout) · ₹24,000
>   #5 Assign Captain C-2210 (deadhead from DEL) · ₹41,200 · 3h delay
>
> Against cancelling: ₹1,500,000
>   81× the recommended option.
>
> Considered 27, 5 legal:
>   −11 qualified: no rating / not active
>   −9 available: rest conflict or double-booked
>   −2 within limits: duty-hour limit exceeded
> ```

Every number there is computed from the operational database and matches
dCortex's published answer key exactly.

---

## 2. The one rule

> ### The model **selects, sequences and narrates.** It never **calculates.**

Every identifier, hour, cost and verdict originates from a deterministic tool
call. The language model understands the question, chooses which tools to run,
and explains the result. That is its entire job.

This is not stylistic. These models are fluent, and fluency is not accuracy —
they will produce a confident, well-worded, entirely invented number when they
lack the real one. Tolerable in a draft email. Not tolerable when a controller
is about to put a specific human being in a cockpit at 05:00.

**Everything below follows from that sentence.**

It is also not theoretical. On a live query in testing, asked only what
RULE-DUTY-02 *says*, the local model replied with a recommendation about a
crew who had exceeded their limits. There was no crew. Nothing had exceeded
anything. The gate caught it and withheld the draft.

---

## 3. The five stages

```
  "Captain of P-2291 is not available on 2026-09-15"
        │
        ▼
  ┌───────────┐  regex extraction, then ~20 ordered patterns
  │  ROUTER   │  → tier 2, FIND_REPLACEMENT, pairing P-2291
  └─────┬─────┘  0 model calls (38/38 gold questions, enforced by a test)
        │
        ▼
  ┌───────────┐  which tools this intent needs, and the opening call
  │  PLANNER  │  → find_options(pairing_id="P-2291", role="Captain")
  └─────┬─────┘  0 model calls — pure Python
        │
        ▼
  ┌───────────┐  ══ THE TRUST BOUNDARY ══
  │ TOOL LOOP │  the model may ask for more; every call is recorded
  └─────┬─────┘  1..N model calls — the only agentic part
        │
        ▼
  ┌───────────┐  every id and number in the prose must appear in the trace
  │ VERIFIER  │  0 model calls — set membership, so it cannot itself hallucinate
  └─────┬─────┘
        │
        ▼
  ┌───────────┐  answer object → controller prose
  │ EXPLAINER │  0 calls on tier 1, 1 on tiers 2–3
  └───────────┘
```

**These are not agents.** They are functions you can step through in a
debugger. Only the tool loop is agentic. At most three model calls per
question, usually one.

Describing them as five agents would be a swarm diagram with nothing behind
it — a judge who asks *"what does your planner agent do?"* would find a
forty-line function that fills in arguments from a regex match. The boring
parts are boring on purpose, so the model cannot get them wrong.

---

## 4. The trust boundary

Eight **tools** sit below it. They are the only source of fact:

| Tool | Answers |
|---|---|
| `lookup` | rows from the dataset — the tier-1 workhorse |
| `duty_clock` | accrued hours and headroom |
| `check_legality` | all seven rules, with the numbers |
| `find_options` | every way to cover a pairing, ranked, with the funnel |
| `ripple` | what a disruption breaks downstream |
| `simulate` | what a perturbation changes |
| `joint_plan` | cost-minimal cover across simultaneous disruptions |
| `explain_rule` | a rule's text and parameters |

Above the boundary the model may only *choose* among these and *narrate* what
comes back. Below it, everything is deterministic Python with unit tests.

**A tool that cannot answer raises rather than guessing.** Returning a
plausible duty hour to keep a demo moving is exactly the failure this design
exists to prevent, so a stub that lies is worse than one that errors.

---

## 5. The layers

```
  L4  devui/     dev console        ← Kiran's Angular app replaces this
  L3  agent/     the five stages, the tool schemas, the verifier
  L2  core/      the rules engine — legality, candidates, cascade, joint
  L1  Postgres   crew, flights, rosters, duty history, certifications
```

Two seams are **protocols**, not imports, which is why backends swap without
touching anything else:

- **`agent.llm.LLM`** — placeholder, Ollama, or a hosted API later
- **`agent.tools.ToolPort`** — JSON, Postgres, fixtures, or the engine

That is why the same console runs on four different data backends with one
environment variable.

---

## 6. What is real

| | State |
|---|---|
| `core/` rules engine | **Real.** All seven rules, verified against dCortex's answer keys. |
| `agent/` router, verifier, explainer | **Real.** |
| Postgres reads | **Real.** Read-only connections; a write raises at the server. |
| Anthropic | **Real.** `claude-opus-5`, 5/5 on tool calls, ~2s, 80% of input served from cache. |
| Groq | **Real.** `qwen/qwen3.6-27b`, 5/5 — free tier is 7,000 input tokens/min. |
| Ollama | **Real.** Local, slower and weaker at arguments — see §8. |
| Conversation | **Real.** Multi-turn state, follow-ups, confirmations. |
| Entity resolution | **Real.** Near-match suggestions, rank checks against the roster. |
| `api/` production API | **Not started** (issue #32). `devui/` is a dev tool. |

### Proof, not assertion

The engine is scored against dCortex's published keys:

| | |
|---|---|
| S1 ATR captain sick | 7/7 options exact |
| S2 flagship 2-day pairing | 6/6 options · day-1 and orphaned day-2 flights · 486 passengers |
| S6 two simultaneous sick calls | 13/13 both aircraft · ₹42,500 joint total · 20 equal-cost ties |
| Q18 legality detail | reproduces the key's wording verbatim |

`pytest -q` → 326 passing.

---

## 7. Traps in the data

Every one of these made the engine **silently wrong** rather than broken. If
you touch `core/`, know them.

**Certification `valid_from` is a generator artifact.** All 150 licence rows
carry a start date years in the future, and C-2087's runs 2028-11-06 to
2026-09-18 — a start after its own end. Enforcing it excludes every pilot in
the airline. RULE-CERT-06 checks **expiry only**.

**Base applies to the first day only.** P-2291 overnights at DEL. Check
RULE-BASE-07 on every day and every BLR captain fails for not being based
where the pairing slept.

**`last_rest_ended` is when rest finished, not when duty released.** Treating
it as a release time and subtracting twelve hours double-counts rest already
taken.

**Duty windows are calendar days, and include earlier days of the same
pairing.** Assign a two-day trip and both days enter the window. Miss it and a
cover looks legal on day 1 and legal again on day 2 when together they breach.
C-3305 is the dataset's teaching case.

**A reserve outside their on-call window is excluded, not repriced.** Someone
rostered on reserve is not on a day off, so falling back to day-off pricing
invents an option the desk does not have.

**S6 has twenty equally optimal answers.** Ten captains at ₹24,000 × two
interchangeable pairings. Never compare `crew_id` when scoring it — check the
total and feasibility, or you fail 19 of 20 correct answers.

**`passengers_affected` is seat capacity, not bookings.** The dataset has no
load data — the only relevant field anywhere is `seats`. dCortex's key uses the
same figure under the same name, so the object keeps it, but the UI should say
"seats at risk". 486 across three A320s is exactly 100% load, which nobody
believes.

**dCortex's own problem statement says "FO C-2087" and C-2087 is a Captain.**
Their dataset README flags it as an erratum. Someone reading their brief will
type it, so a stated rank is checked against the roster and queried rather than
accepted.

---

## 8. What the model is actually for

A fair challenge: if routing is regex, the tools compute, and the verifier
polices the prose — why is there a model at all?

Because the regex only knows what we wrote down. Measured on phrasings a real
controller would use and that no gold question contains:

| | Unseen phrasings |
|---|---|
| Regex alone | **2/10** |
| Model alone | **6/10** |
| What ships (regex, model on fallback) | **6/10** |

The 38/38 routing figure is **memorisation** — those patterns were tuned on
those questions. The 2/10 is the honest generalisation number. Quote both or
neither.

The model also composes multi-step plans the planner cannot express, and
writes the prose a controller reads. What it is measurably **bad** at is
bookkeeping: it invented dates outside the dataset, and passed the literal
string `"BLR->BOM"` as a pairing id even after being told the format twice.

**So the rule of thumb: every time the model fails at bookkeeping, move that
step below the trust boundary rather than prompting harder.** Flight → pairing
resolution is deterministic now for exactly this reason.

### Where the verifier cannot help

Four times now the model has produced something false that the gate passed,
because the fabrication carried no number or identifier to check:

1. Asked what RULE-DUTY-02 *says*, it warned about a crew who had exceeded
   their limits. There was no crew.
2. It returned its entire chain of thought as the answer — every figure in it
   sourced, none of it a response.
3. It rewrote "there is no crew C-1045" into "C-1045 isn't rostered this
   week", a different claim about someone who does not exist.
4. Asked which of three dates a controller meant, it answered on their behalf
   and narrated whichever it preferred — so the same question gave different
   answers on different runs.

**The gate proves claims are sourced. It cannot prove the prose describes what
happened.** Every one of these was fixed by taking work away from the model:
tier-1 answers are not polished, reasoning is suppressed at the source, tool
errors are rendered verbatim, and a clarifying question ends the turn.

---

## 9. Talking to it

`Advisor.ask()` is stateless by design. `Conversation` (in
`agent/conversation.py`) holds the session, which is what makes it an advisor
rather than a report generator:

```
"C-1042 is sick"      -> ranked options
"why not C-2087?"     -> DUTY-02, over by 1h20m on the 15th
"what about C-2210?"  -> legal, ranked #5, ₹41,200 and a 3h delay
"go with C-3310"      -> recorded
```

Most of that costs nothing. A candidate search already returns every excluded
crew member with their reason, so "why not X" is a lookup into the answer from
a moment ago rather than a new search.

Two rules hold here. **Context resolves against the last turn that produced
candidates**, not the previous turn — by the time a controller decides they
may have asked two clarifying questions. And **decisions are recorded, not
executed**: a dearer choice is flagged and allowed, a choice the rules engine
excluded is refused with the breach quoted. The desk decides.

### Questions the system asks back

Three things stop a turn and put a question to the controller, rather than
guessing:

| | |
|---|---|
| An id that does not exist but has a near match | *"There is no C-1024. Did you mean C-1042 (Captain, BLR)?"* |
| A stated rank the roster contradicts | *"C-2087 is a Captain, not a First Officer."* |
| An ambiguous reference | *"DX412 operates on three dates. Which do you mean?"* |

These come back with `awaiting` set, and the next turn answers them. **A near
match is never substituted silently** — C-1042 and C-1024 differ by one
transposed digit, and one of them is nobody.

---

## 10. If you are changing something

1. **Never let the model compute.** Needing it to add two numbers means a tool
   is missing. This binds the *renderer* too — a template that printed
   "and 11 more" was doing arithmetic no tool produced, and the verifier
   rightly rejected the whole answer.
2. **Typed object first, prose rendered from it.** The eval harness scores the
   object.
3. **Never rename an `Option` field.** The first seven are the answer-key
   contract; renaming one breaks scoring silently.
4. **A tool that cannot answer raises.**
5. **Ties are first-class.** Where several plans cost the same, say so.
6. **Run `pytest -q` before pushing** — and check its exit code rather than
   piping it through `tail`, which masks it. The answer-key tests are what let
   you refactor `core/` and know immediately if you broke it.
7. **Nothing fails silently.** An empty answer is a bug: if no tool ran, say
   what was understood and what is missing. "No data was returned" reads as
   "nothing is wrong", which is the one thing this must never imply.
