# RULES.md — the 7 rules, and the two traps

Source of truth: [`crew-ops-advisor-dataset/data/rules.json`](../crew-ops-advisor-dataset/data/rules.json). Params come from that file — never hardcode a number here into logic.

**Read this before writing a line of LEX.** Two conventions in this dataset will silently produce plausible-but-wrong answers, and wrong legality answers are the one failure mode we cannot ship.

---

## Definitions (from `rules.json`)

| Term | Meaning |
|---|---|
| **Duty period** | `report_utc` → `release_utc` |
| **Report** | first departure **− 60 min** |
| **Release** | last arrival **+ 30 min** |
| **FDP** | Flight Duty Period = duty period length, in hours |
| **Sector** | one flight leg |
| **Reserve callout** | legal only if the callout time falls **inside** the on-call window. Once assigned, they operate as line crew and the window no longer applies. |

All times UTC. Currency INR.

---

## ⚠ Trap 1 — windows are CALENDAR-DAY, not rolling

`RULE-DUTY-02` (7 days) and `RULE-FLT-03` (28 days) use **UTC calendar-day windows, inclusive of the duty date** — *not* rolling 168-hour / 672-hour windows from the current instant.

```
  duty date 2026-09-15, 7-day window
  ├── 2026-09-09  ← inclusive start
  ├── 2026-09-10
  ├── … 
  └── 2026-09-15  ← inclusive end (the duty date itself)
```

Sum `daily_history[].duty_hours` across those dates. `daily_history` in `duty_clocks.json` covers 2026-08-18 → 2026-09-14 precisely so this is computable on any day of the week.

> **Canary test:** Q02 — C-1042's duty hours for the 7 calendar days ending 2026-09-14 must be **20.93h**, leaving **39.07h** headroom under the 60h cap. If you get this, your window math is right. If you get anything else, stop and fix it before writing another rule.

---

## ⚠ Trap 2 — FDP limit shrinks with sector count

`RULE-FDP-01` is **not** a flat 13 hours.

```python
fdp_limit_hours = 13.0 - 0.5 * max(0, n_sectors - 2)
```

| Sectors | Limit |
|---|---|
| 1–2 | 13.0h |
| 3 | 12.5h |
| 4 | **12.0h** |
| 5 | 11.5h |
| 6 | 11.0h |

Scenario S4 turns on exactly this: a tech delay stretches a 4-sector duty past 12.0h, so the rostered crew cannot legally finish the tail legs — and the delay *creates* a fresh crewing problem.
---

## The 7 rules

| Rule ID | Text | Params | Implementation note |
|---|---|---|---|
| `RULE-FDP-01` | Max flight duty period 13h, reduced 0.5h per sector beyond the 2nd | `base_fdp_hours: 13.0`<br>`reduction_per_extra_sector_hours: 0.5`<br>`free_sectors: 2` | See Trap 2. Compute per duty **day**, not per pairing. |
| `RULE-DUTY-02` | Max 60 duty hours in any 7 consecutive calendar days | `max_duty_hours: 60`<br>`window_days: 7` | See Trap 1. Must include the **prospective** duty when simulating a cover. Check **every** day of a multi-day pairing — a cover can be legal on day 1 and breach on day 2 (C-3305 is the teaching case). |
| `RULE-FLT-03` | Max 100 block hours in any 28 consecutive calendar days | `max_flight_hours: 100`<br>`window_days: 28` | Same window logic as DUTY-02, on `flight_hours`. |
| `RULE-REST-04` | Min 12h rest between release and next report | `min_rest_hours: 12` | Check **both** sides — rest before the new duty *and* rest before whatever the candidate is already rostered for next. |
| `RULE-QUAL-05` | Crew must hold a valid rating for the assigned aircraft type | — | `crew.ratings` vs `flights.aircraft_type`. Ratings are `A320` / `ATR72`. C-2091 is ATR-only — the exclusion case. |
| `RULE-CERT-06` | All certifications must be valid on the duty date | — | 4 cert types per crew in `certifications.json`. Check **`valid_to ≥ duty_date` only** — not `valid_from ≤ duty_date` too — for **every** cert, on **every** day of the pairing. See Trap 3 below. |
| `RULE-BASE-07` | Reserve callout from own base only; covering from another base requires deadhead positioning (cost applies) | — | See below. |

---

## RULE-BASE-07 — deadhead positioning

Covering from a different base is legal but costs positioning plus the delay it forces.

**The DEL → BLR positioning flights:**

| Flight | Arrives BLR | Runs on |
|---|---|---|
| `DX402` | 08:45Z | odd dates |
| `DX589` | 07:45Z | even dates |

- New report time = **positioning arrival + 15 min**
- Cost = `reserve_callout` + `deadhead_positioning` + (delay hours × `delay_cost_per_duty_hour`)
- If there is no same-day positioning flight from the candidate's base, they are excluded with reason `RULE-BASE-07: no same-day positioning flight from base`

**Worked example — C-2210 (DEL), the demo beat:**
```
  18,500  reserve callout (pilot)
 +  6,500  deadhead positioning
 + 16,200  3h delay × ₹5,400/duty-hour
 ─────────
   41,200  total, DX412 departs ~3h late, zero cancellations
```
Compare: cancelling a single leg is **₹250,000**. That contrast is the argument the advisor should make out loud.

---

## Reserve on-call windows

A reserve is usable when the **required report time** — *after* any deadhead positioning — falls inside their `oncall_window_utc`. Not the disruption time. Not the departure time. The report time.

```
  C-3305  BLR  00:00–05:30   ← early window
  C-3310  BLR  06:00–18:00
  C-3315  BLR  03:00–15:00
```

C-3305 is a deliberate teaching case: legal for day 1 of P-2291 in isolation, but breaches `RULE-DUTY-02` on day 2. A cover must be legal for **the whole pairing**, not just the leg in front of you.

---

## Verdict shape

Every predicate returns a trace, never a bare boolean:

```python
RuleVerdict(
    rule_id  = "RULE-DUTY-02",
    status   = "FAIL",                       # PASS | FAIL | NOT_APPLICABLE
    detail   = "would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)",
    used     = 61.33,
    limit    = 60.0,
    headroom = -1.33,
    date     = "2026-09-15",
)
```

Match the answer-key phrasing where it exists — `questions.json` Q18 expects exactly:

```
"RULE-DUTY-02: would exceed 60h/7d by 1h20m on 2026-09-15 (total 61.33h)"
```

The harness compares structured fields, not prose, but matching the wording makes failures obvious at a glance and makes the UI read like the rulebook.

---

## Engineered facts to test against

From the dataset README — these reproduce the problem-statement examples exactly:

- `C-1042` (A. Nair, Captain, BLR) operates 2-day pairing `P-2291` — day 1 `DX412/DX413/DX588`, day 2 `DX589/DX590/DX591`
- `C-2087` covering P-2291 breaches `RULE-DUTY-02` by **1h20m** (61.33h vs 60h)
- `C-3310` covers cleanly at **₹18,500**
- `C-2210` (DEL) is legal via deadhead at **₹41,200**
- `C-3305` is legal day 1, breaches day 2
- `C-2091` is ATR-only — the `RULE-QUAL-05` exclusion
- One flagged roster exception: cabin crew `C-5417`, `recurrent_training` expires 2026-09-17 but rostered 2026-09-19 → scenario S5
