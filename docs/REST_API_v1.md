# REST API — v1 (hackathon day 1)

**Status: 🟢 v1 scope — freeze today. Optimisation questions go to the organisers tomorrow.**

## The split

| Layer | Transport | Powers | Owner |
|---|---|---|---|
| **View layer** | plain REST, JSON, deterministic, cacheable, no LLM | flights board, HITL alerts, crew view, sidebar — **everything you see** | Gayathri (routes) + Kashifa (`core/` functions) |
| **Advisor** | `POST /ask` SSE stream | the chat bubble (bottom-right) + scenario runs only | Shashank |

**One core, two façades.** Every REST endpoint and every agent tool call the *same* function in `core/`. The agent's tools are a subset of these endpoints. No logic is duplicated, and the LLM/deterministic boundary stays exactly at the REST edge.

## Conventions

- Base `/api/v1` · JSON in/out · times ISO-8601 UTC · money integer INR · hours float 2dp.
- **`date` / `as_of` query param on every read.** Default = snapshot `2026-09-14` / `2026-09-14T18:00:00Z`. Valid dates `2026-09-14 … 2026-09-20`.
- Lists take `?limit=&cursor=` (data is tiny, but keep the shape).
- Every derived response carries **`basis`** — the files + rule IDs it was computed from. Explainability is scored; make it structural.
- Errors: `{ "error": { "code": "...", "message": "...", "hint": "..." } }` — codes `BAD_PARAM · NOT_FOUND · UNRESOLVED_ENTITY · INTERNAL`.
- CORS open; dev server proxies `/api` → `:5000` (`frontend/proxy.conf.json`).

---

## 1. System & reference — app bootstrap, popovers

| # | Method | Path | Params | Returns | Consumed by |
|---|---|---|---|---|---|
| 1 | GET | `/health` | — | `{world_loaded, crew, flights, mode}` | boot check |
| 2 | GET | `/meta` | — | `{snapshot_utc, week:{start,end}, hub:"BLR", currency:"INR", counts:{crew,flights,pairings,reserves}}` | date-picker bounds, header |
| 3 | GET | `/rules` | — | `RuleDef[]` `{rule_id, text, params, gloss}` | 7-rule trace labels, "explain rule" popover |
| 4 | GET | `/rules/{rule_id}` | — | `RuleDef` + worked example | rule popover |
| ~~5~~ | ~~GET~~ | ~~`/stations`~~ | — | **DROPPED from v1** — no consumer; station codes derive from `/flights`. | — |
| ~~6~~ | ~~GET~~ | ~~`/aircraft`~~ | — | **DROPPED from v1** — no consumer; tail/type/seats ride on `FlightRow`. | — |
| 7 | GET | `/costs` | — | rate card — `costs.json` verbatim (the real keys) | cost breakdowns; kept in `ApiPort` |

---

## 2. Flights — main display (daily board, colour-coded by delay rank)

| # | Method | Path | Params | Returns | Consumed by |
|---|---|---|---|---|---|
| 8 | GET | `/flights` | `date` (req) · `station?` · `aircraft?` · `status?` · `delay_rank?` · `sort?` | `FlightRow[]` | **the main board** |
| 9 | GET | `/flights/{flight_id}` | — | `FlightDetail` | flight click-through |
| 10 | GET | `/flights/{flight_id}/downstream` | `delay_min?` | ordered tail legs (same aircraft **and** same pairing) with cumulative delay propagation | mini-cascade on click; feeds the colour rank |
| 11 | GET | `/pairings/{pairing_id}` | — | `PairingDetail` `{days:[{date,flights,report_utc,release_utc}], crew:[{crew_id,role}], overnight_station}` | flight detail + crew detail cross-link |
| 12 | GET | `/pairings/{pairing_id}/candidates` | `role` · `callout_utc` · `delay_h?` | `{funnel:[…], options:Option[], near_misses:Option[], excluded:[{crew_id,verdicts}]}` — **deterministic, no LLM** | "who can cover this" panel; agent calls the same endpoint |

**`FlightRow`**
```jsonc
{ "flight_id":"DX412-2026-09-15", "flight_no":"DX412", "date":"2026-09-15",
  "dep_station":"BLR", "arr_station":"DEL", "dep_utc":"...", "arr_utc":"...",
  "aircraft":"VT-DXC", "aircraft_type":"A320", "seats":162, "pairing_id":"P-2291",
  "status":"scheduled",                 // scheduled | at_risk | delayed | cancelled
  "delay_rank":"critical",              // critical | high | medium | low   ← colour
  "delay_rank_score":83,                // 0–100
  "delay_rank_reasons":["tail slack 20m < 30m","pairing overnights at DEL"],
  "slack_minutes":20,                   // to next dep on the same tail
  "downstream_count":4,
  "crew_fdp_headroom_min":45,
  "basis":["flights.json","rosters.json","rules.json"] }
```

### `delay_rank` — the colour formula (give this to Gayathri verbatim)

Proactive mini-RIPPLE over every flight. `slack_minutes` = next-tail-departure − this-arrival. `crew_fdp_headroom_min` = FDP limit − projected duty for the operating pairing that day.

| Rank | Any of |
|---|---|
| **critical** | `slack < 30` · crew FDP/duty headroom `< 30` min · pairing overnights away from base (day-2 orphan risk) · `downstream_count ≥ 4` on the tail today |
| **high** | `slack < 60` · headroom `< 60` · `downstream_count ≥ 2` |
| **medium** | `slack < 120` · `downstream_count == 1` |
| **low** | otherwise (last leg of the day / ample slack) |

`delay_rank_score` = weighted blend of the same signals, 0–100, so the board can sort. Always return `delay_rank_reasons[]`.

**`FlightDetail`** = `FlightRow` + `{ crew:[{crew_id,name,role,rank}], report_utc, release_utc, block_hours, pax_estimate, prev_leg, next_leg, operating_crew_pressure:[{crew_id, rule_id, headroom, status}] }`

---

## 3. HITL alerts — top-right panel

| # | Method | Path | Params | Returns | Consumed by |
|---|---|---|---|---|---|
| 13 | GET | `/alerts` | `date?` · `status?` (`open`\|`ack`\|`resolved`) · `severity?` · `type?` | `Alert[]` newest first | alert panel |
| 14 | GET | `/alerts/{id}` | — | `Alert` + expanded context object | alert expand |
| 15 | POST | `/alerts/{id}/ack` | body `{by?}` | updated `Alert` | "acknowledge" |
| 16 | POST | `/alerts/{id}/resolve` | body `{note?, decision_id?}` | updated `Alert` | "resolve / dismiss" |

**`Alert`**
```jsonc
{ "id":"AL-014", "type":"DUTY_LIMIT_NEAR",
  // DUTY_LIMIT_NEAR | CERT_EXPIRING | FLIGHT_AT_RISK | RESERVE_POOL_LOW
  // | ROSTER_EXCEPTION | DISRUPTION_REPORTED | RESOLUTION_PROPOSED
  "severity":"warning",                 // critical | warning | info
  "subject":{ "kind":"crew", "id":"C-2087" },   // crew | flight | pairing | station | reserve_pool
  "title":"C-2087 within 1h20m of 60h/7d limit",
  "detail":"Projected 58.6h by 2026-09-16 if rostered as planned.",
  "created_utc":"2026-09-14T18:05:00Z",
  "status":"open",
  "suggested_action":{ "label":"Ask the advisor", "ask_prompt":"C-2087 is near the duty limit — what are my options?",
                       "deep_link":"/crew/C-2087" },
  "payload": null }                      // RESOLUTION_PROPOSED carries Option[] here for approve/reject
```

Alert generation = a deterministic scan over the world at load + after any simulate. Rules of thumb: `CERT_EXPIRING` ≤ 3 days · `DUTY_LIMIT_NEAR` headroom < 3h · `RESERVE_POOL_LOW` a base+role pool ≤ 1 · `ROSTER_EXCEPTION` straight from `rosters.json.flagged_exceptions`.

---

## 4. Crew view — list + filters + detail

| # | Method | Path | Params | Returns | Consumed by |
|---|---|---|---|---|---|
| 17 | GET | `/crew` | `date?` · `filter?` (`needs_attention`\|`on_duty`\|`off_duty`\|`on_reserve`\|`all`) · `role?` · `base?` · `status?` · `q?` | `CrewRow[]` | crew list |
| 18 | GET | `/crew/{crew_id}` | `date?` | `CrewDetail` | crew click-through |
| 19 | GET | `/crew/{crew_id}/duty-clock` | `date?` · `prospective_pairing?` | calendar-day window sums, 7d/28d headroom, rest status | headroom widgets |
| 20 | GET | `/crew/{crew_id}/legality` | `pairing_id` · `delay_h?` | `RuleVerdict[]` — all 7 rules for this crew vs a pairing | "can X cover Y" on the detail panel |
| 21 | GET | `/crew/{crew_id}/assignments` | `from?` · `to?` | this week's pairings/legs with report/release | crew detail timeline |
| 22 | GET | `/reserves` | `date?` · `base?` · `role?` · `covers_report_utc?` | `Reserve[]` `{crew_id, base, role, window, covers:bool, reachability_minutes}` | sidebar + cover flows |

**`CrewRow`**
```jsonc
{ "crew_id":"C-2087", "name":"...", "rank":"Captain", "base":"BLR",
  "ratings":["A320"], "status":"active", "on_duty":false,
  "current_assignment":{ "pairing_id":null, "flight_id":null },
  "next_report_utc":"2026-09-16T04:00:00Z",
  "duty_7d":48.6, "duty_7d_headroom":11.4,
  "disruption_risk_score":0.31,
  "attention":{ "flag":true, "reasons":["RULE-DUTY-02 headroom 1.4h < 3h"] },
  "basis":["duty_clocks.json","certifications.json","risk_signals.json"] }
```

**`CrewDetail`** = `CrewRow` +
```jsonc
{ "seniority":14, "reachability_minutes":90,
  "duty_clock":{ "duty_7d":48.6, "duty_7d_headroom":11.4, "flight_28d":82.0,
                 "flight_28d_headroom":18.0, "last_rest_ended":"...", "rest_ok":true },
  "certifications":[ { "type":"licence", "valid_from":"...", "valid_to":"2026-09-18",
                      "days_to_expiry":4, "expiring_soon":true } ],
  "risk":{ "score":0.31, "drivers":["..."] },
  "reserve_window":null }
```

**"needs_attention"** = cert `expiring_soon` (≤3d) OR duty/flight headroom `< 3h` OR `flagged_exception` OR `disruption_risk_score ≥ 0.7`. Always return `attention.reasons[]`.

---

## 5. Sidebar — one aggregate call + the panels

| # | Method | Path | Params | Returns | Consumed by |
|---|---|---|---|---|---|
| 23 | GET | `/summary` | `date` | `{crew:{on_duty,off_duty,reserve,needs_attention}, flights:{total,on_time,at_risk,delayed,cancelled}, alerts:{critical,warning}, reserves:{by_base_role:{…}, depleted:[…]}, aircraft:{in_service,aog}, stations:{closures:[…]}}` | whole sidebar in one request |
| ~~24~~ | ~~GET~~ | ~~`/stations/{code}/status`~~ | **DROPPED from v1** — weather/closures out of scope. | — |
| 25 | GET | `/risk-signals` | `threshold?` · `date?` | pre-computed risk list (provided input — **not** a model) | sidebar watch-list |

---

## 6. Advisor — chat bubble + scenarios (SSE, agent)

| # | Method | Path | Body | Returns | Notes |
|---|---|---|---|---|---|
| 26 | POST | `/ask` | `{query, as_of?, weights?, stream}` | `text/event-stream` — `status·tool_call·tool_result·rule_check·token·answer·abstain·done` | **built** — `docs/CONTRACT_RECONCILIATION.md` |
| 27 | GET | `/scenarios` | — | `S1…S6` | built |
| 28 | POST | `/scenarios/{id}/run` | `{stream}` | SSE (same events) | built |
| 29 | POST | `/rank` | `{options, weights}` | reordered `Option[]`, no LLM — policy-slider path | built |
| 30 | POST | `/crew/{crew_id}/notification` | `{pairing_id}` | `{draft}` — callout message (Tier-3 bonus) | agent-backed, or template |

---

## 7. What-if & consequence — REST (deterministic; also the agent's tools)

| # | Method | Path | Body | Returns | Consumed by |
|---|---|---|---|---|---|
| 31 | POST | `/ripple` | `{event}` | `blast_radius` `{nodes,flights,aircraft,passengers,edges[]}` | flight/alert "show impact" |
| 32 | POST | `/simulate` | `{event}` | `world_diff` `{before,after,changed[]}` + re-run alerts | "what if I delay 40m instead" |
| 33 | POST | `/joint-plan` | `{events[]}` | cost-minimal joint assignment (S6) | stretch |

`event` shape: `{ type:"SICK_CREW"|"DELAY"|"STATION_CLOSURE"|"CERT_EXPIRY"|"MULTI_SICK", ... }` (matches `scenarios.json`).

---

## 8. Decisions — audit trail (the "no reasoning trail" pain point)

| # | Method | Path | Body | Returns | Consumed by |
|---|---|---|---|---|---|
| 34 | POST | `/decisions` | `{disruption_ref, chosen_option, weights, accepted:bool, note?}` | `{id, ...}` | "apply / stage this option"; logs preference pairs (README §5) |
| 35 | GET | `/decisions` | `date?` | `Decision[]` | decision log panel |

v1: in-memory store is fine.

---

## UI element → endpoints

| UI element | Endpoints |
|---|---|
| Header / date picker | 2 `/meta` |
| **Main board — flights list** | 8 `/flights?date=` → 9 `/flights/{id}` → 10 `/downstream`, 11 `/pairings/{id}` on click |
| **HITL alerts (top-right)** | 13 `/alerts` (poll ~15s or on focus) · 15 `/ack` · 16 `/resolve` · 31 `/ripple` for "show impact" · alert `RESOLUTION_PROPOSED` → 34 `/decisions` |
| **Sidebar** | 23 `/summary` (one call) · 24 station status · 25 risk-signals · 22 `/reserves` |
| **Crew view — list** | 17 `/crew?filter=needs_attention` etc. |
| **Crew detail (click)** | 18 `/crew/{id}` · 19 `/duty-clock` · 20 `/legality?pairing_id=` · 21 `/assignments` |
| **Chat bubble (bottom-right)** | 26 `/ask` (SSE) · 29 `/rank` for sliders · 30 notification draft |
| **"Who can cover this" (from a flight)** | 12 `/pairings/{id}/candidates` (deterministic) |
| Rule popovers / legality trace labels | 3 `/rules`, 4 `/rules/{id}` |

---

## Ownership

- **Gayathri** — routes 1–25, 31–35 in `api/app.py` over `core/`. This doc is the mapping; response shapes above.
- **Kashifa** — the `core/` functions the routes call: `world` loader, `duty_clock`, all 7 `lex` rules → `RuleVerdict`, `cost`, `candidates` (funnel), `delay_rank`, alert scan.
- **Shashank** — 26–30; agent tools = thin wrappers over the same `core/` functions (routes 12, 19, 20, 31, 32).
- **Kiran** — consumes everything; builds `api/data_mock.py` today (REST mock returning the shapes above from the vendored dataset) so the console is unblocked before `api/app.py` exists. Same mock→real flip as the SSE side.

## Not in v1 (organiser conversation tomorrow)

Optimiser for joint/multi-event assignment (33 stays heuristic), passenger rebooking, live weather feed, multi-agent escalation, auth.
