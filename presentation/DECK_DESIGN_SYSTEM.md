# Deck Design System — dCortex Crew Ops Advisor

**Purpose:** the visual contract for the hackathon presentation deck. Paired with
[`DECK_SPEC.md`](DECK_SPEC.md), which is the slide-by-slide content doc. Feed both to Claude Design.

**Provenance:** every token in §2 is lifted verbatim from `https://dcortex.ai/assets/css/style.css`
(fetched 2026-09-05). Anything *not* on that site is in §3 and labelled **EXT** — extensions we add
because a projected 16:9 deck has needs a scrolling website does not. Nothing here is invented brand.

**Canvas:** 1920 × 1080, fixed. All sizes below are absolute px on that canvas — the site's fluid
`clamp()` values have already been resolved at 1920px viewport, then adjusted for projection (§4).

---

## 1. The visual thesis in one line

> Bone paper and near-black, DM Sans at heavy weights and tight tracking, one electric green
> that means *signal*, hairlines instead of shadows — and the turn of every sentence set in
> **italic green**.

dCortex.ai does four things repeatedly. The deck does the same four things and almost nothing else:

1. **The italic green punchline.** A statement in bone, then the turn in italic green.
   Site hero: "When plans meet reality" — bone line, then `#7ed321` italic. This is the signature.
2. **Full-bleed green interstitial.** An entire viewport of `#7ed321` carrying two dark words
   ("Built to act."). Used sparingly — it is the loudest thing in the system.
3. **Eyebrow → giant heading → 46ch body.** Green uppercase micro-label, then a heading at
   800–900 weight and `-0.025em`, then one restrained paragraph. Never more.
4. **Hairline grids, no shadows.** Everything is separated by 1px borders at 7% opacity.
   There is not a single box-shadow on the site except the green glow on a live dot.

---

## 2. Tokens (verbatim from dcortex.ai)

### 2.1 Colour

```css
:root {
  /* grounds */
  --bg:        #f7f5f1;   /* bone paper — the light ground */
  --bg-alt:    #f0ede8;   /* bone, one step down — alternating light sections */
  --card-bg:   #ffffff;   /* card on bone */
  --dark:      #07090b;   /* near-black — the primary deck ground */
  --dark-alt:  #0d1008;   /* near-black with a green cast — the "trust band" ground */

  /* ink */
  --text:      #0d0d0d;   /* ink on bone */
  --muted:     rgba(13,13,13,0.44);

  /* signal */
  --green:     #7ed321;   /* THE brand colour. Signal, live, pass, emphasis */

  /* hairlines */
  --border:        rgba(0,0,0,0.07);       /* on bone */
  --border-dark:   rgba(255,255,255,0.07); /* on near-black */
  --border-dark-2: rgba(255,255,255,0.10); /* screenshot frames */

  /* motion */
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
}
```

**Ink-on-dark ladder** — the site expresses all secondary text as bone at an alpha. Resolved:

| Role | Value | Resolved | Contrast on `--dark` |
|---|---|---|---|
| Primary | `#f7f5f1` | — | **18.32:1** |
| Body / list item | `rgba(247,245,241,0.72)` | `#b4b3b1` | **9.52:1** |
| Deck / description | `rgba(247,245,241,0.52)` | `#848483` | **5.33:1** |
| Caption **EXT floor** | `rgba(247,245,241,0.62)` | `#9c9b9a` | **7.19:1** |

> ⚠️ The site's `0.45` and `0.42` tiers resolve to **4.20:1** and **3.80:1**. `0.42` fails AA for
> body text and both are unreadable projected in a lit room. **The deck floor is `0.62`.**
> Do not use `.feature-body` / `.trust-body` alphas as-authored.

### 2.2 The brand gradient

```css
background: linear-gradient(135deg, #2563eb 0%, #7ed321 40%, #eab308 80%, #2563eb 100%);
background-size: 250% 250%;
animation: gradient-shift 2.2s ease infinite;   /* hover state on .dcx-btn */
```

Stops: blue `#2563eb` · green `#7ed321` · yellow `#eab308`. Plus `#f87171` (the site's red).

**This is the whole legality legend, already in the brand.** See §3.2 — we did not pick four new
colours, we named the four the brand already owns.

### 2.3 Type

```
DM Sans — weights 500, 600, 700, 800, 900
https://fonts.googleapis.com/css2?family=DM+Sans:wght@500;600;700;800;900&display=swap
```

Site heading behaviour, which the deck inherits exactly:

- Headings: **800–900** weight, `letter-spacing: -0.025em`, `line-height: 1.05–1.08`
- Giant numerals: **900**, `letter-spacing: -0.05em`, `line-height: 0.88`, unit at `0.28em`
- Eyebrow: **700**, `letter-spacing: 0.24em`, `text-transform: uppercase`, colour `--green`
- Body: **500** (the site never sets body below 450)
- Quotes: **700**, `letter-spacing: -0.01em`, `line-height: 1.38`

### 2.4 Geometry

| Token | Value | Where |
|---|---|---|
| Card radius | `16px` | proof cards, quote cards, founder photos |
| Screen frame radius | `14px` | `.platform-screen` — **the screenshot frame** |
| Pill radius | `9999px` / `100px` | buttons, live pills |
| Small radius | `8px` | inline chips |
| Accent bar | `1.75rem × 2px`, radius `2px`, `--green` | above every feature/trust title |
| Live dot | `0.42rem` circle, `--green`, `box-shadow: 0 0 8px var(--green)` | the only shadow on the site |
| Side margin @1920 | `112px` (`clamp(2rem,7vw,7rem)` resolved) | every section |

---

## 3. Extensions (EXT) — not on the site, added deliberately

Flagged so nobody mistakes these for brand heritage.

### 3.1 A monospace face

The site has none. The product cannot do without one: `PRODUCT.md` requires operational values
(hours, costs, verdicts, rule IDs) at true tabular density, and every crew ID, `₹` figure and
`RULE-XXX-NN` on these slides must align in a column.

```
DM Mono — weights 400, 500
https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&display=swap
font-feature-settings: "tnum" 1;
```

**Why DM Mono:** it is the designed sibling of DM Sans — same foundry, same skeleton. It reads as
the brand rather than as a borrowed terminal font. Fallback: `ui-monospace, SFMono-Regular, monospace`.

**Rule:** every number, ID, timestamp and rule citation is DM Mono. Prose is DM Sans. No exceptions —
the split between the two faces *is* the trust boundary rendered typographically.

### 3.2 The legality legend

Four semantic inks, each a stop of the brand gradient. On `--dark` ground:

| Token | Value | Meaning | Contrast on `--dark` | Text token (never colour alone) |
|---|---|---|---|---|
| `--pass` | `#7ed321` | rule satisfied | **10.66:1** | `PASS` |
| `--near` | `#eab308` | near-miss — legal via deadhead/delay | **10.40:1** | `NEAR` |
| `--breach` | `#f87171` | rule violated | **7.21:1** | `FAIL` |
| `--ref` | `#60a5fa` | reference / not applicable | **7.84:1** | `N/A` |

> The site's blue is `#2563eb`, which is **3.86:1 on near-black — fails AA**. `--ref` is that blue
> lightened to `#60a5fa` for dark grounds. Keep `#2563eb` for use on bone only (4.75:1).

**Binding:** status is *never* carried by colour alone (`PRODUCT.md` §Accessibility, dim-room
context). Every verdict renders as `ink + uppercase text token + glyph` (`✓ PASS`, `✗ FAIL`, `△ NEAR`).

### 3.3 Green as text on bone — don't

`#7ed321` on `#f7f5f1` is **1.72:1**. It is decorative-only on light grounds. The live site sets
green eyebrows on bone in `#proof`; do not copy that.

| Use | Token | Value | Contrast on bone |
|---|---|---|---|
| Green **text** on bone **EXT** | `--green-ink` | `#457312` | **5.19:1** |
| Green **fills** on bone (bars, dots, ground) | `--green` | `#7ed321` | n/a — not text |
| Dark text on green ground | `--dark` | `#07090b` | **10.66:1** ✓ |

Light-ground semantic set **EXT**: `--near-ink #8a5c00` (5.34), `--breach-ink #b91c1c` (5.94),
`--ref-ink #1e40af` (8.01).

### 3.4 Projection floor

Website body copy resolves to 15–17px at 1920. Projected across a room that is unreadable.
**No text on any slide is below 20px.** Full scale in §4.

---

## 4. Type scale — fixed, 1920 × 1080

| Role | Size | Weight | Tracking | Leading | Face |
|---|---|---|---|---|---|
| `display` — cover only | 124px | 900 | -0.025em | 1.02 | Sans |
| `statement` — section headline | 80px | 800 | -0.025em | 1.05 | Sans |
| `statement-turn` — the italic green line | 80px | 900 *italic* | -0.025em | 1.05 | Sans |
| `sub` — secondary headline | 56px | 800 | -0.02em | 1.1 | Sans |
| `numeral` — giant stat | 144px | 900 | -0.05em | 0.88 | Sans |
| `numeral-unit` | 40px | 700 | 0.01em | — | Sans |
| `lead` — one paragraph under a statement | 28px | 500 | 0 | 1.6 | Sans |
| `body` | 24px | 500 | 0 | 1.65 | Sans |
| `card-title` | 26px | 700 | -0.01em | 1.35 | Sans |
| `card-body` | 20px | 500 | 0 | 1.7 | Sans |
| `quote` | 40px | 700 | -0.01em | 1.38 | Sans |
| `eyebrow` | 16px | 700 | 0.24em | 1 | Sans |
| `micro` — card label, caption | 14px | 700 | 0.20em | 1.3 | Sans |
| `data` — tabular values | 22px | 500 | 0 | 1.55 | **Mono** |
| `data-sm` — dense traces, funnel | 20px | 400 | 0 | 1.7 | **Mono** |

Measure: `lead` and `body` cap at **46ch** (the site's `.sec-desc` max-width). Never wider.

---

## 5. Grid & spacing

```
Canvas          1920 × 1080
Side margin     112px          → content width 1696px
Top margin       96px          → eyebrow baseline zone
Bottom margin    88px
Columns         12 × 116px, gutter 32px   (12·116 + 11·32 = 1744 ≈ 1696 + bleed tolerance)
Vertical rhythm 8px base; block gaps 24 / 40 / 64 / 96
```

**Bleed is allowed and encouraged** off the right and bottom edges only — the site bleeds
`.platform-screen` and hero media. Never bleed off the left (the eyebrow/heading edge is the
spine of the whole deck).

---

## 6. Slide grounds — the rotation

The site alternates dark → green → dark → bone → dark. The deck does the same, and the rotation
carries meaning:

| Ground | Value | Reserved for |
|---|---|---|
| **Night** | `--dark #07090b` | default. Problem, architecture, every screenshot slide (the console is dark) |
| **Green** | `--green #7ed321` | interstitial only. 2–4 words, `--dark` ink, 800 weight. Max **3 per deck** |
| **Bone** | `--bg #f7f5f1` | proof, numbers, evaluation, the honesty slide — "we step into the light to show our work" |
| **Trust band** | `--dark-alt #0d1008` | the limits / what-we-didn't-build slide |

Never put two green interstitials adjacent. Never put a console screenshot on bone.

---

## 7. Components

### 7.1 Eyebrow
```
16px · 700 · 0.24em · uppercase · --green  (on bone: --green-ink)
margin-bottom 40px
```
Always present, always top-left at the margin. It is the deck's page number and its rhythm.

### 7.2 Statement + italic turn — **the signature**
```
Line 1   statement (80px/800/bone)
Line 2   statement-turn (80px/900/italic/--green)
gap      0.08em
```
Example: `The model selects, sequences and narrates.` / *`It never calculates.`*
Use on at most 6 slides. It loses its force if every headline does it.

### 7.3 Feature item
```
green bar   28 × 2px, radius 2, --green, margin-bottom 16
title       card-title, bone
body        card-body, rgba(247,245,241,0.62)
```
Grids of 3 or 5 (the site uses `repeat(3,1fr)` and `repeat(5,1fr)` with a top hairline).

### 7.4 Stat card — the before/after
```
card        --dark ground, radius 16, padding 56, gap 24
label       micro · 0.20em · uppercase · --breach (before) / --green (after)
numeral     144px/900/-0.05em/0.88 · same colour as label
unit        40px/700, vertical-align 0.12em, margin-left 0.3em
desc        card-body · rgba(247,245,241,0.62)
```
Two side by side, 1fr 1fr, gap 24. On a **bone** slide the cards stay `--dark` — that inversion
is the site's actual move in `#proof` and it is the strongest single frame in the system.

### 7.5 Quote card
```
--card-bg, radius 16, 1px --border, padding 48
quote 40px/700/-0.01em/1.38 --text
who   micro · uppercase · --muted, margin-top 24
```
Bone slides only.

### 7.6 Numbered column (01 / 02 / 03)
```
number  40px/900/--green (bone: --green-ink)
title   card-title
body    card-body
```
Hairline-separated, `repeat(3,1fr)`.

### 7.7 Live pill
```
radius 100px · background rgba(126,211,33,0.18) · border 1.5px rgba(126,211,33,0.55)
padding 12 24 12 16 · backdrop-filter blur(12px)
box-shadow 0 0 28px rgba(126,211,33,0.18), 0 2px 12px rgba(0,0,0,0.3)
dot 10px --green with `ping` keyframe (75%,100% { scale(2.2); opacity 0 }) 1.6s
text 20px/700 bone
```
Use for the live/status marker on the demo slide and the cover.

### 7.8 Data table / trace block
```
Mono `data-sm`, tnum on
row height 44px, 1px --border-dark between rows, no vertical rules, no zebra
rule ID column left-aligned and fixed width; verdict column = ink + text token + glyph
numbers right-aligned
```
No table ever gets a fill. Hairlines only.

### 7.9 Pill button (for the closing CTA / demo cue only)
```
--green ground, --dark ink, radius 9999, padding 14 32, 20px/700
```

### 7.10 Screenshot frame — see §8. This is the most-used component in the deck.

---

## 8. Screenshots — capture, framing, layouts

The site already has this component: `.platform-screen`. We use it as-authored.

```css
.screen {
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,0.10);   /* on bone: 1px rgba(0,0,0,0.07) */
  overflow: hidden;
  background: #07090b;                         /* prevents a white flash behind a loading image */
}
.screen img { width: 100%; display: block; }
```

No drop shadow. No perspective tilt. No browser chrome, no fake macOS traffic lights. The console
is presented as a flat plate, because it is evidence, not a product mockup.

### 8.1 Capture spec

| | |
|---|---|
| Viewport | **1920 × 1080**, DPR 2 → 3840 × 2160 PNG |
| Component crops | capture the element bounding box + 24px padding, DPR 2 |
| Theme | the console's dark ground (`PRODUCT.md`: dim-room default) |
| Chrome | browser UI cropped out entirely before the file is saved |
| Data | seeded scenarios only — S1…S6. Never a half-loaded or `—` state unless the slide is *about* that state |
| Naming | `presentation/assets/NN-surface-detail@2x.png` (e.g. `09-funnel@2x.png`) |
| Redaction | none needed — synthetic dataset, no real PII |

> Capture **before** the deck is built. A slot sized to a screenshot that does not exist yet is the
> single most common way a hackathon deck falls apart at T+22.

### 8.2 The eight captures to take

Numbered to the slides in `DECK_SPEC.md` that consume them.

| # | File | Surface / component | Slide | Frame |
|---|---|---|---|---|
| C1 | `13-console-board@2x.png` | `features/board` — full console, flights board colour-coded by `delay_rank`, alert panel populated | 13 | Whole (L-E) |
| C2 | `09-funnel@2x.png` | `components/funnel` — 150 → 32 → 21 → 12 → 6, drop reason per stage | 9 | Detail (L-D) |
| C3 | `10-rule-trace@2x.png` | `components/rule-trace` + `rule-chip` — all 7 verdicts, one FAIL with its trace | 10 | Detail (L-D) |
| C4 | `08-blast-radius@2x.png` | `components/blast-radius` — P-2291 cascade incl. orphaned day-2 | 8 | Split (L-B) |
| C5 | `11-options-card@2x.png` | `components/options-card` — ranked options with the ₹41,200 deadhead near-miss visible | 11 | Split (L-B) |
| C6 | `14-abstain-card@2x.png` | `components/abstain-card` — the "I can't answer that reliably" surface | 14 | Split (L-B) |
| C7 | `12-trace-panel@2x.png` | `components/trace-panel` — live tool-call trace mid-stream | 12 | Triptych |
| C8 | `12-crew-drawer@2x.png` | `features/crew` detail drawer — duty clock, expiring certs, per-pairing legality | 12 | Triptych |
| C9 | `12-policy-sliders@2x.png` | `components/policy-sliders` — weights + re-ranked list | 12 | Triptych |

### 8.3 Screenshot layouts — exact slots at 1920 × 1080

**L-A · Bleed** — headline over a screen that runs off the bottom edge. The site's own gesture.
```
eyebrow      x 112  y 96
statement    x 112  y 148 … 268     (80px, max 2 lines)
lead         x 112  y 300           (28px, 46ch, optional)
screen       x 112  y 380  w 1696  h 954 (16:9 native)  → bleeds 254px past the bottom
```
Use when the *top* of the console carries the point. Never when the point is in the lower third.

**L-B · Split** — text left, screen bleeding off the right edge. The workhorse: 4 of 9 captures.
```
eyebrow      x 112  y 96
statement    x 112  y 160 … 340     (56px `sub`, max 3 lines)
body/list    x 112  y 400 … 900     (w 672 — hard 46ch measure)
screen       x 896  y 220  w 1136  h 639 (16:9)  → bleeds 112px past the right edge
```
For component crops (4:3 or free), keep `x 896`, `w 1136`, centre vertically in `y 180…900`.

**L-C · Triptych** — three *component crops*, never three full consoles.
```
each screen  w 512  h 384 (4:3)   gaps 40   row x-start 152
screen row   y 420
caption      micro, --green, 24px below each frame, one line, max 40ch
eyebrow      x 112 y 96 · statement x 112 y 150…290 (56px)
```
> A full console scaled to 512px wide is illegible. Triptych slots take **component-level captures
> only** — one card each.

**L-D · Detail** — full screen plus a magnified crop, connected. For the funnel and the rule trace.
```
screen        x 112   y 300  w 1100  h 619 (16:9)
              → draw a 2px --green box, radius 8, around the source region inside it
connector     2px --green rule from the box edge to the inset's left edge
inset         x 1120  y 380  w 688   h 480   (the crop, .screen frame, 14px radius)
inset label   micro --green, above the inset
```
This is the slide where a judge sees that the funnel is real UI and not a diagram. It earns the
extra construction.

**L-E · Whole** — one screenshot, uncropped, nothing competing.
```
screen       x 192  y 124  w 1536  h 864 (16:9)
eyebrow      x 192  y 1016 (baseline row, left)
caption      x 800  y 1016 · 20px/500 · rgba(247,245,241,0.62) · right-aligned to x 1728
```
Exactly one slide uses this: the console reveal at slide 13.

### 8.4 Annotating a screenshot

Only two annotation marks exist. Do not invent a third.

1. **Green box** — 2px `--green`, radius 8, around a region. Nothing inside it changes.
2. **Numbered pin** — 32px `--green` circle, `--dark` numeral 18px/900, with a 2px green leader
   line to a `micro` caption in `--green` set outside the frame.

Dim-the-rest is banned: darkening the un-annotated 90% of a dark console makes it unreadable on a
projector.

### 8.5 If a capture is missing at build time

Place a **placeholder plate**: `.screen` frame at the correct slot, ground `#0d1008`, centred
`micro` text in `--green`: `CAPTURE PENDING · C4 · blast-radius`. Never a stock image, never a
sketch, never a stretched crop of a different surface. A visible gap is honest; a substitute is not.

---

## 9. Motion

The deck is presented live and may be exported to PDF. **Every slide must read correctly frozen.**

| Move | Spec | Where |
|---|---|---|
| Reveal | `opacity 0→1`, `translateY(14→24px → 0)`, `0.45–0.65s var(--ease)`, stagger 60ms | list items, cards, feature grid |
| Ping | `scale(1→2.2)`, `opacity 0.6→0`, `1.6s cubic-bezier(0,0,0.2,1)` infinite | live dot only |
| Gradient shift | `background-position 0%→100%→0%`, `2.2s ease` infinite | the closing CTA pill only |

No slide transitions beyond a hard cut. No parallax. No 3D. Honour `prefers-reduced-motion`.

---

## 10. Guards — binding, from `PRODUCT.md`

These constrain the visuals, not just the copy. A design that violates one is wrong even if it looks good.

1. **Advisor, not autopilot.** Nothing may be styled as the system deciding or acting. No
   "auto-resolve" affordance, no winner-crown/trophy on the rank-1 option, no green "APPLY" that
   implies execution. Rank 1 is distinguished by *position and a hairline*, not by a victory badge.
2. **Seven rules, no more.** Legality visuals must never imply broader regulatory coverage than
   `RULE-FDP-01 … RULE-BASE-07`. Always show all seven, always name them.
3. **Colour is never the only channel.** Every verdict, status and delta carries a text token.
4. **No invented numbers on any slide.** Every figure traces to `crew-ops-advisor-dataset/`,
   `evals/harness.py` output, or the rate card. Unmeasured slots stay as `⟨FILL⟩` until measured.
   This is the rubric's own line: *overstating capability scores badly*.
5. **Don't write "multi-agent."** It is a pipeline with three model calls (`README.md` §11.1).

---

## 11. Do / Don't

| Do | Don't |
|---|---|
| One idea per slide, one focal region | Two competing headlines |
| Green for signal — bars, dots, the italic turn, PASS | Green as body text on bone (1.72:1) |
| Hairlines at 7% | Drop shadows, glows (except the live dot) |
| DM Mono for every number and ID | Proportional figures in a cost column |
| Flat screenshot plates | Tilted/perspective device mockups, browser chrome |
| Bleed right and bottom | Bleed left — it breaks the spine |
| Max 3 green interstitials | A green slide next to a green slide |
| 20px text floor | Copying the site's 15px `.feature-body` |
| `⟨FILL⟩` where a number is not yet measured | A plausible-looking placeholder number |

---

## 12. Asset manifest

```
presentation/assets/
  00-cover-bg.(jpg|mp4 poster frame)      optional — night ops imagery, heavily overlaid
  08-blast-radius@2x.png                  C4
  09-funnel@2x.png                        C2
  10-rule-trace@2x.png                    C3
  11-options-card@2x.png                  C5
  12-trace-panel@2x.png                   C7
  12-crew-drawer@2x.png                   C8
  12-policy-sliders@2x.png                C9
  13-console-board@2x.png                 C1
  14-abstain-card@2x.png                  C6
```

Cover imagery, if used, sits under the site's own two overlays:
```css
background: linear-gradient(105deg, rgba(7,9,11,0.82) 0%, rgba(7,9,11,0.60) 50%,
                                    rgba(7,9,11,0.25) 80%, transparent 100%);
background: linear-gradient(to top, rgba(7,9,11,0.45) 0%, transparent 35%);
```
