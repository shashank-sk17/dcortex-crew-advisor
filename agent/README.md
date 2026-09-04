# `agent/` — the Advisor Layer (L3)

The natural-language layer of the Crew Ops Advisor. It turns a controller's
question into tool calls, proves the answer is sourced, and explains it back.

> **No network calls are made anywhere in this package.** `PlaceholderLLM`
> returns canned responses so the whole pipeline runs — and all 116 tests pass —
> with no API key, no SDK, and no `core/`. See [§7](#7-what-is-real-and-what-is-a-placeholder).

```bash
python -m agent.cli "Who is on reserve at BLR on 2026-09-15?"
python -m agent.cli --entities   "Can C-1042 cover P-2291 on 15 Sep?"
python -m agent.cli --route-only "Both captains are sick — give the optimal plan"
python -m agent.cli --stream     "What does RULE-DUTY-02 say?"
pytest agent/tests/ -q
```

---

## 1. The one rule

> ### The model **selects, sequences and narrates.** It never **calculates.**

Every identifier, hour, cost and verdict in an answer originates from a
deterministic tool call. The model chooses which tools to call and puts the
result into a controller's language. That is its entire job.

This is not a style preference. A crew controller is accountable for what they
do with the answer, at 05:00, with an aircraft on stand. An answer that *might*
contain an invented duty hour is worse than no answer, because it costs them
the time to verify it themselves — which is the time we were supposed to save.

Everything in this package follows from that sentence.

---

## 2. The pipeline

```
  "Captain C-1042 called in sick for P-2291. Who do I use?"
        │
        ▼
  ┌───────────┐   entities.py — regex, exact, never statistical
  │  ROUTER   │   router.py   — tier + intent, rules first, model only if they abstain
  └─────┬─────┘   → Route(intent=FIND_REPLACEMENT, tier=2, crew=C-1042, pairing=P-2291)
        │
        ▼
  ┌───────────┐   advisor.py — seed_calls() opens with what the entities imply,
  │  PLANNER  │                tools_for() narrows the schema list to this intent
  └─────┬─────┘
        │
        ▼
  ┌───────────┐   tools.py — THE TRUST BOUNDARY
  │ TOOL LOOP │   everything below here is deterministic Python in core/
  └─────┬─────┘   every call is recorded as a TraceEntry
        │
        ▼
  ┌───────────┐   verifier.py — every id and number in the prose must appear
  │ VERIFIER  │                 in the trace. Set membership, not a model.
  └─────┬─────┘   fail → fall back to the template renderer and say so
        │
        ▼
  ┌───────────┐   explainer.py — templates first, model polish second
  │ EXPLAINER │                  polish may reword; it may not add a fact
  └─────┬─────┘
        ▼
   AdvisorResponse — typed object; prose is rendered FROM it, never the reverse
```

---

## 3. Why one agent and not several

We evaluated a multi-agent decomposition — a legality agent, a cost agent, a
cascade agent, a coordinator — and rejected it.

All the hard reasoning here is **already deterministic**. LEX evaluates seven
rules exactly. RIPPLE traverses a graph. JUDGE sorts by a published rate card.
JOINT solves a small assignment problem. A multi-agent system would have
language models conferring about work that `core/` computes exactly and
instantly, paying serial round-trips for zero added correctness — on a desk
whose entire value proposition is speed.

Multi-agent earns its place when subtasks need genuinely different context that
will not co-exist in one window, or when fan-out over a large noisy search
space needs isolated reasoning. Our whole world is 700 KB and every candidate
is scored by a pure function. Neither condition holds.

**Name it honestly.** What is above is a *pipeline* with up to three model
calls. It is not a multi-agent system and should not be described as one — to
a judge, to a README, or on a slide. A defended negative decision is
architecture; a cargo-culted swarm diagram is not. (`DECISIONS.md` #13)

---

## 4. Routing: rules first, model last

`route()` tries ~15 ordered patterns before it will consider a model call.
**All 38 gold questions route to dCortex's own tier label — 38/38**, with no
model involved, and `test_router.py` fails on the first regression.

That matters for three reasons: the common path costs nothing, it is
reproducible, and every decision reports which rule fired (`matched_rule`), so
a misroute is debuggable rather than mysterious.

The model is consulted only when every rule abstains. If it is unavailable or
returns something unparseable — which is what the placeholder does — the router
degrades to `LOOKUP_CREW` at `LOW` confidence and records why. A lookup reads
data and changes nothing, so it is the safe thing to guess.

**Tier is derived from intent, never decided separately.** `Intent.tier` is the
only source, so the two cannot drift apart.

### The entity/intent split

```
  "can C-1042 cover P-2291 on the 15th?"
        ├─► REGEX  → C-1042, P-2291, 2026-09-15    exact, no ranking
        └─► DENSE  → CHECK_LEGALITY, tier 2         fuzzy, shape only
```

Identifiers never go through an embedding. `C-1042` and `C-1024` are nearly
identical in vector space, and resolving the wrong captain is the worst failure
this system has. `test_entities.py` asserts they stay distinct.

`entities.py` also resolves dates a controller would actually type — `15 Sep`,
`Sep 15`, `2026-09-15`, `the 15th` — the last only because the dataset is one
fixed week, and only when it lands inside it.

---

## 5. Retrieval: why there is barely any

The full exemplar corpus is **776 tokens** (38 prompts) plus ~120 (7 rule
texts). That is smaller than a single retrieval round-trip, so the exemplars
ship inside the **cached system prompt** and the router sees all 38 rather than
a top-3 approximation. Strictly more accurate, and no index to build, warm or
invalidate.

**No BM25.** It is a statistical approximation of exact matching, and we have
exact identifiers with known formats. Regex beats it outright and never
mis-ranks. Its other job — topical matching — is near-useless on a corpus where
all 38 documents share one vocabulary ("captain", "pairing", "sick", "reserve").
If two rankers are ever fused, use Reciprocal Rank Fusion: raw BM25 scores and
cosine similarities are not on a common scale, so a fixed 0.5/0.5 blend of them
is arbitrary.

**No reranker.** A cross-encoder over 38 candidates costs more latency than the
retrieval it corrects.

`exemplars.py` still ships a cosine index, for the one corpus that will
actually grow — the decision audit log — and for `explain_rule`. It is a NumPy
dot product on purpose: 38×384 floats is 58 KB, and an ANN index costs more to
build than the scan it replaces. Two details that matter:

- **IDs are masked before embedding.** `"Captain C-1042 calls in sick"` →
  `"Captain <CREW> calls in sick"`. This collapses Q17 and S1 onto one
  template, which is exactly right when the question is *what kind of ask is
  this*. Biggest single accuracy win on the intent path.
- **It abstains below 0.5 similarity.** A misleading exemplar is worse than
  none — it steers the planner confidently into the wrong toolchain.

---

## 6. The verifier

The part that makes the demo credible, and deliberately **not** a language
model — it is set membership over the trace, so it cannot itself hallucinate.

```python
trace = [TraceEntry(tool="lookup", result={"crew_id": "C-1042", "cost_inr": 18500})]

verify("C-1042 costs 18,500.", trace).ok    # True
verify("C-9999 costs 18,500.", trace).ok    # False — C-9999 came from nowhere
verify("C-1042 costs 22,750.", trace).ok    # False — invented number
```

It handles the things that would otherwise produce false verdicts: `₹18,500`
and `18500` normalise to the same value; floats compare within tolerance;
numbers buried in a rule's prose (`"exceeds by 1h20m (total 61.33h)"`) count as
evidence; nested tool results are walked to any depth; and arguments the model
passed *in* are evidence too, since they came from the controller or an earlier
result.

Two calibrations worth knowing:

- **Identifiers are stripped before numbers are scanned.** Otherwise `C-1042`
  contributes `1042` — which both invents a claim and, far worse, would let a
  fabricated *"1042 hours"* pass. This was a real bug caught by
  `test_partial_support_still_fails`.
- **Small integers are prose, not claims.** "all 7 rules", "the 2 options" need
  no source. `VERIFIER_NUMERIC_FLOOR` draws the line, and non-integers are
  always claims — a 3.5-hour delay is a real quantity.

**When the gate fails**, the advisor falls back to the deterministic template
renderer (which can only restate tool output), drops confidence to `MEDIUM`,
and puts the reason in `unknowns`. It never ships the unsourced draft.

---

## 7. What is real and what is a placeholder

| Module | State |
|---|---|
| `entities.py` | **Real.** Full extraction and masking, 30 tests. |
| `router.py` | **Real.** 38/38 tier accuracy on the gold set. |
| `verifier.py` | **Real.** Complete gate, 20 tests. |
| `explainer.py` | **Real.** Deterministic renderer for all three tiers. |
| `schemas.py` | **Real.** Mirrors `docs/API_CONTRACT.md`. |
| `exemplars.py` | **Real**, with `HashingEmbedder` standing in for a sentence model. |
| `advisor.py` | **Real** orchestration; drives whatever `LLM` and `ToolPort` it is given. |
| `llm.py` | **Placeholder.** `AnthropicLLM` raises `NotImplementedError`. |
| `tools.py` | **Partial.** `lookup` and `explain_rule` read the real dataset; the rest raise `ToolError`. |

Two things are deliberate here.

**`PlaceholderToolPort` refuses rather than invents.** `check_legality` raises
`ToolError` instead of returning a plausible verdict. Returning a made-up duty
hour to keep the demo moving is precisely the failure this architecture exists
to prevent, and a stub that lies is worse than one that errors. The advisor
handles it correctly: confidence drops to `LOW` and the reason surfaces in
`unknowns`.

**Both swap points are protocols, not imports.** Nothing depends on a vendor
SDK or on `core/` — only on `agent.llm.LLM` and `agent.tools.ToolPort`.

### Wiring in the real model (issue #24)

Implement `AnthropicLLM.complete` and `.stream` against the Messages API,
keeping the return types unchanged. The docstring in `llm.py` lists what
matters: models come from `config`, the system prompt and tool definitions get
cache breakpoints (long, static, hit every turn), vendor tool-use blocks map
onto `ToolCall`, streaming deltas map onto `StreamEvent`, and
`stop_reason == "tool_use"` must be propagated because `advisor.py` loops on
it. Confirm parameter names against the current SDK rather than from memory.

### Wiring in the real core (issues #1–#12)

Write `CoreToolPort` satisfying `ToolPort`, backed by Kashifa's `World`. Both
implementations must pass `evals/contract_test.py`, which is what makes the
swap a no-op.

---

## 8. Layout

```
agent/
├── README.md         this file
├── config.py         models, dataset paths, vocabulary, thresholds
├── schemas.py        Tier · Intent · Option · RuleVerdict · AdvisorResponse
├── entities.py       regex extraction + ID masking
├── router.py         tier/intent classification
├── exemplars.py      gold-question corpus, masking, cosine index
├── tools.py          tool schemas · ToolPort · PlaceholderToolPort · dispatch
├── verifier.py       the trust gate
├── explainer.py      answer object → prose, citations
├── advisor.py        the loop
├── llm.py            LLM port + placeholder client   ← swap point
├── cli.py            python -m agent.cli
├── prompts/
│   ├── __init__.py   assembly + per-intent guidance
│   └── system.md     role, rulebook, rate card, house style
└── tests/            116 tests, no network, no key
```

## 9. Design rules for anyone editing this

1. **Never let the model compute.** If you find yourself asking it to add two
   numbers, that is a missing tool.
2. **Typed object first, prose second.** The harness scores the object.
3. **A tool that cannot answer must raise, not guess.**
4. **New tool → add to `TOOL_SCHEMAS`, `ToolPort`, and `_INTENT_TOOLS`.** The
   last one is what keeps a tier-1 lookup from being handed `joint_plan`.
5. **Never rename an `Option` field.** The first seven are the answer-key
   contract; renaming one breaks scoring silently.
6. **Ties are first-class.** Where several plans cost the same they are equally
   correct — say so rather than presenting one as uniquely right
   (`DECISIONS.md` #12).
