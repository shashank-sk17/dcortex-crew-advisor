# presentation/

Everything for the hackathon **presentation deck and live demo** — deliverables §5.7 and §8 of the
problem statement.

```
presentation/
├── README.md                  ← you are here
├── DECK_SPEC.md               slide-by-slide content: 20 slides + 7 appendix
├── DECK_DESIGN_SYSTEM.md      visual contract, derived from dcortex.ai
├── assets/                    screenshots C1–C9, cover imagery
└── build/                     exported deck (PDF/PPTX) + backup demo video
```

## The two documents

| File | What it is | Who uses it |
|---|---|---|
| [`DECK_SPEC.md`](DECK_SPEC.md) | Every slide's ground, layout, exact copy, screenshot slot, timing, and the rubric line it serves. Includes the demo beat sheet and both running orders (10-min and 15-min). | Whoever writes the deck; whoever presents it |
| [`DECK_DESIGN_SYSTEM.md`](DECK_DESIGN_SYSTEM.md) | Colour, type, grid, components, motion, and the five binding guards. Tokens lifted verbatim from `dcortex.ai/assets/css/style.css`; extensions marked **EXT**. §8 is the screenshot capture and framing spec. | Whoever builds the slides |

Feed **both** to Claude Design. Neither is complete alone — the spec names components the design
system defines, and the design system's layout slots are consumed by the spec.

## Order of work

1. **Capture the screenshots first.** `DECK_DESIGN_SYSTEM.md` §8.2 lists the nine
   (`C1`–`C9`) with their source component, target slide and frame. A slot sized to a screenshot
   nobody has taken is the standard way a deck falls apart at T+22.
2. **Run `evals/harness.py`** and fill every `⟨FILL⟩` token in `DECK_SPEC.md` slides 16 and 18.
3. **Pick the real failure case** for slide 14 from that run. Do not invent one — §7 of the brief:
   *"Honest failure analysis scores well; overstating capability scores badly."*
4. **Build the slides.**
5. **Export to PDF into `build/`** and check every slide reads correctly frozen, with no motion.
6. **Bank the backup demo video into `build/`** at T+21 (`PROGRESS.md` milestone M5).

## Two hard rules

- **`⟨FILL⟩` never ships as a guess.** Every one is a number nobody has measured yet. An empty cell
  we name beats a number we invent.
- **Read every slide against the five guards** in `DECK_DESIGN_SYSTEM.md` §10 before export —
  advisor not autopilot, seven rules only, never colour alone, no invented numbers, don't write
  "multi-agent".

## Conventions

- Bare paths in both documents (`PRODUCT.md`, `evals/harness.py`, `crew-ops-advisor-dataset/`,
  `frontend/src/app/components/`) are **repo-root relative**, not relative to this folder.
- The problem statement PDF stays at the repo root
  (`problem_explanation_k66g3nx88t.pdf`) — it is the brief for the whole project, not just the
  deck, and `README.md` and `PRODUCT.md` both reference it there.
- Screenshots are named `NN-surface-detail@2x.png` where `NN` is the consuming slide number.

## Source of truth

The deck states no fact that isn't already in one of these:

| | |
|---|---|
| `problem_explanation_k66g3nx88t.pdf` | the brief — problem, tiers, rubric weights, scoring principles |
| `PRODUCT.md` | users, positioning, binding guards, brand commitments |
| `README.md` | architecture, the five organs, the trust boundary, defended negatives |
| `PROGRESS.md` | the eval scorecard — the number that goes on slide 16 |
| `crew-ops-advisor-dataset/` | every figure, crew ID, rule and rate on any slide |
