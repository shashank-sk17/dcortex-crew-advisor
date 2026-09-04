# `devui/` — agent test console

A debugging instrument for the advisor. Type a controller's question, watch
every pipeline stage fire, and inspect what each one returned.

```bash
python -m devui.server        # http://localhost:8420
```

Standard library only — no Flask, no npm, no build step. Start it and open the
page.

> **This is not the product.** The controller-facing console is Kiran's Angular
> workspace in [`frontend/`](../frontend) (issues #31–#39). This is a
> disposable dev tool that runs the agent in-process; nothing else should
> import from it. It is here so all four of us can exercise L3 before `api/`
> and `core/` exist.

---

## What it shows

**The pipeline strip** across the top is the point. Five stages, each reporting
what it did, each clickable for its full output:

| | |
|---|---|
| **Router** | tier + intent, which pattern matched, whether the model was consulted, the masked form of the query |
| **Planner** | which tools were offered for this intent, which were seeded from the extracted entities |
| **Tool loop** | every call with arguments, timing, result and error |
| **Verifier** | every claim in the answer, checked against the trace |
| **Explainer** | the rendered narrative |

Stage colour is the fastest read on the page:

- **teal — ok.** Ran on real data.
- **violet — degraded.** Ran, but something underneath is a placeholder: the
  model, or a tool `core/` has not implemented.
- **red — failed.** The verifier found an unsupported claim; the answer was
  withheld and the template renderer used instead.

**The verifier ledger** on the right lists every identifier and number in the
answer with the tool that sourced it. A red row is a claim nothing supports —
which, on a real model, means a hallucination the gate caught.

---

## Try these

Tier 1 works end to end today. Tier 2 and 3 will show **degraded** until the
legality engine lands — that is the correct behaviour, not a bug. An unbuilt
tool raises rather than returning a plausible duty hour.

| Question | What it demonstrates |
|---|---|
| *Who is on reserve at BLR on 2026-09-15?* | full green path, 21 claims all sourced |
| *What does RULE-DUTY-02 say?* | rule lookup, citations populated |
| *If C-2087 covers P-2291, does any rule breach?* | honest degradation — `check_legality` refuses |
| *Both A320 captains are sick. Give the optimal joint plan.* | S6 shape routes to `JOINT_PLAN`, tier 3 |
| *Can C-1042 cover for C-2087 on P-2291?* | two crew ids, **not** a joint plan |

The left rail holds all 38 gold questions grouped by dCortex's own tier label.
A **red question id** means our router disagreed with that label — currently
none do, so any red is a regression you just introduced.

---

## Endpoints

| | |
|---|---|
| `GET /api/state` | what is live and what is a stub |
| `GET /api/questions` | the 38 gold prompts with routed tier and intent |
| `POST /api/ask` | `{"query": "..."}` → full per-stage breakdown |
| `GET /api/stream?q=` | SSE in the shape `docs/API_CONTRACT.md` specifies |

`/api/stream` is worth pointing a terminal at — it emits the real
`tool_call` / `tool_result` / `token` / `done` sequence, which is what Kiran's
console will consume:

```bash
curl -N "localhost:8420/api/stream?q=What+does+RULE-REST-04+say%3F"
```

---

## Notes

- **`#q=...` deep-links a run.** The URL updates as you go, so a failing case
  can be pasted into Slack and reproduced exactly.
- **Nothing is persisted.** Every request re-runs the pipeline from scratch.
- **No API key, no network.** `PlaceholderLLM` drives the loop; the explainer
  stage will read *degraded* until a real client is wired up (issue #24).
