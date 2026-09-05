# Design Brief — dCortex Crew Ops Console (redesign)

**Status:** confirmed via `/impeccable shape` · **Mode:** Operate · **Direction:** Enroute Chart (concept seed `f7882d05`, assigned index 4)
**Inputs:** `PRODUCT.md`; the critique at `.impeccable/critique/2026-09-04T09-55-51Z__frontend-src-app.md` (24/40).
**This is a brief, not a build.** No code and no direction contract are written yet; those come at build time.

---

## 1. Job & audience

A night-shift airline crew controller opens the console cold at 05:00 because a disruption just hit. In minutes she must see what's affected, which flights are now at risk (including downstream legs of the same pairing), which crew can *legally* move, who's reachable, what it costs — then commit and hand the decision to the next shift. Dim room, sustained focus, a countdown, twenty years on the desk, distrusts anything that acts on its own. Secondary audience: judges at a live demo; desk usability wins every trade-off.

## 2. Outcome & proof

- **Primary task:** disruption → legally-verified, cost-ranked, cited resolution → recorded decision.
- **Success:** she trusts it enough to act, and it says so when it can't. Every number on screen traces to a data row + a rule ID.
- **Product-specific proof a competitor can't copy-paste:** the 7-rule legality trace as bounded regions with a published legend; the candidate funnel (150 → 6, drop reason per stage); the pairing cascade / blast radius; "the answer isn't always a person" (deadhead / delay / re-crew / cancel, with the cost contrast shown).
- **Binding guards:** advisor, not autopilot — nothing may read as the system deciding or acting. The 7 named rules (RULE-FDP-01 … RULE-BASE-07) are the whole rulebook.

## 3. Selected direction — *Enroute Chart*

**Thesis.** The console owns the aeronautical-chart language the controller already reads. Legality is drawn as **bounded regions with a legend that is part of the document** — a candidate is inside the legal region, or outside it by a measured amount. It refuses the near-black KPI-dashboard-with-a-chat-bubble (what the current build is) and its friendly-light-SaaS opposite.

**Own-world.** Night-chart ground `#0d1a1f`; chart-white linework `#e8eef0`; a **semantic ink set that functions as the legend** — legal green `#5fbf7f`, near-miss amber `#e0a53d`, breach magenta `#d94f7a`, reference blue `#3aa0c8`. Engraved hairline linework, hatched restricted regions, boxed figure reserves (MSA-style) for hard numbers. One measured monospace face at true tabular density carries every operational value; the chart lines only organise. No chrome the chart language doesn't define. (Palette, mark vocabulary, and the face are set precisely at build against Jeppesen reference — see §7.)

**Raised (named donations from the hands it beat).**
- *from Datamatics* — operational values (hours, costs, margins, verdicts) set in one monospace face at real tabular density, as the composition itself.
- *from Alphabet Storm* — applying a disruption is **one deliberate, reversible redraw**: before-state → after-state, changed regions briefly held in transition ink. Always the SANDBOX diff, never decoration.
- *from Orizuru* — the resolution is a **numbered sequence** (assess → funnel → legality → options → commit); every completed step stays on screen with its result, one marker on the active step, the committed decision reads as the sum of its steps.
- *from Departure Board (competitive alternate)* — the arrival / triage surface is a **live, time-ranked register** where a change announces itself physically (a row restyles + a brief flap/settle) so the eye is pulled to what just moved.

**Structural bet — invert figure and ground.** Selecting a disruption opens an always-on **reasoning workspace** as the main panel — funnel + 7-rule legality chart + blast radius + ranked options + the signed bottom line. The conversational advisor becomes an **optional narration layer over it**, not a bubble you summon to get the real answer.

**Focal moment.** The legality chart resolving — seven rules drawn as regions, the candidate's position plotted against each, the breach called in human units ("1h20m outside RULE-DUTY-02 on 15 Sep") — beside the funnel that got you there.

**Cross-surface reach.** The same chart grammar carries the flights board (routes on a time axis), the crew view (a crew member's week plotted against their duty / rest / cert envelopes), the alert queue (each alert a marked position on the network chart), and the decision log (stamped entries in the margin).

**Honest risk.** Cartography can read decorative or get busy, and a 05:00 desk needs faster triage than a static chart affords. Mitigated by the live time-ranked register as the arrival surface, and by ruthless suppression — the chart is calm until a disruption is selected, then it commits.

## 4. Scope & boundaries

- **Fidelity:** confirmed brief now; build scope decided next against time remaining.
- **Breadth when built:** four surfaces — arrival / board, disruption workspace, crew view, alert queue — plus the decision-log close and the advisor-as-narration layer. One visual world across all.
- **Untouched:** `PRODUCT.md` truth; the REST contract (`docs/REST_API_v1.md`) and the `ApiPort` seam; the SSE advisor event contract (`docs/CONTRACT_RECONCILIATION.md`); the mock ↔ real swap mechanism; all copy that states domain fact.
- **Anti-goals:** no KPI-tile sidebar; no summoned chat bubble as the primary answer path; no colour-only status; no "auto-resolve" or winner-styling on the recommendation; no rulebook framing beyond the 7 rules; no roster mutation (commit = record a decision).

## 5. States & ranges

- **Board rows:** ~15–40 flights/day across the week; 0 on a quiet slice → real empty state, not a bare header row.
- **Disruption:** 1 typical; up to simultaneous / multi (scenario S6). Event types: sick crew, station closure, tech delay, cert expiry.
- **Candidate funnel:** 150 → 6 legal (+0–2 near-miss); excluded list 6–20.
- **Legality:** 7 verdicts always rendered; PASS / FAIL / N/A / pending (streams in).
- **Options:** 1–6 legal + near-misses; or `NO_LEGAL_OPTION` (a real answer, shown with near-misses).
- **Material states:** first-run / cold arrival; loading and **stale** (last-good timestamp + retry); **error per region** (critique P0); disruption-selected; resolution-in-progress; committed / recorded; `confidence: low` / abstain; dim-room default.

## 6. Interaction & layout

- **Topology:** a persistent left legend / nav rail (the 7 rules, always readable); a main stage that is the **live board** at rest and the **reasoning workspace** when a disruption is selected; a right column for ranked options + the signed bottom line; the decision log reachable from the rail; the advisor as a dockable narration strip over the workspace, not a floating FAB.
- **Hierarchy:** one focal region at a time. At rest, the time-ranked "needs you now" set leads; everything else recedes. Selected, the legality chart + funnel lead.
- **Feedback:** every fetch has loading / stale / error / retry; a connection state near the environment badge; the disruption redraw is the one orchestrated transition; a change on the live register restyles the row and settles (respect `prefers-reduced-motion`).
- **Affordances:** full keyboard model — list navigation (↑/↓ / j/k), "/" to focus search, a key to open the advisor, Esc closes any overlay; real `:focus-visible` on every control; the tables are semantic `<table>`s with headers; status carries a text token, not just ink; `aria-live` on the streaming answer.
- **Commit:** a deliberate "record decision" step (note optional) → the option, its cost, its rule check, and a timestamp land in the log; the item leaves the queue as *resolved*, distinct from *acknowledged*, with undo.
- **Responsive:** desktop-first (the control-room width); the rail collapses to an icon strip with a restore control (never vanishes); the workspace stacks below the board on narrow.

## 7. Constraints & open decisions

- **Platform:** web; Angular 19 standalone + signals + SCSS; no UI-lib dependency added without cause.
- **Delivery:** code-led (no image generation this session) — ambition lives in §3's first viewport + the named signature transition, audited at the finish review.
- **Accessibility:** WCAG AA contrast (the current `--fg-3` at ≈2.6:1 fails and must be re-based); status never by colour alone; full keyboard path; screen-reader announcement of the stream and state changes; dim-room legibility is a first-class constraint.
- **Reuse:** keep `ApiPort` / `AdvisorService` / `ConversationStore` / `reduceTurn`; the answer-card components (`rule-chip`, `funnel`, `options-card`, `blast-radius`) are **re-skinned into the chart grammar, not rebuilt**.
- **A builder must not invent:** the chart's mark vocabulary and legend (defined at build against Jeppesen reference), the monospace face (measured / ranked at build), the exact redraw choreography, the decision-log schema beyond `postDecision`. Flag these at build start; do not guess.
- **Open:** whether the crew view gets the full envelope-chart treatment in v1 or a lighter pass; whether the advisor strip is docked-by-default or opened on the first `NO_LEGAL_OPTION`.

---

## Next

- Decide build scope against time remaining (whole console vs. one flow: disruption → resolution → recorded).
- At build start, `/impeccable` new-work writes the `## Direction contract` into a surface brief, then builds the Enroute Chart world for real. DESIGN.md is written at finish from the built world.
