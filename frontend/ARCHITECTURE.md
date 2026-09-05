# Frontend architecture — how a request flows, component by component

## 0. Two backends, and where the real ones sit

| Channel | Frontend entry point | Real backend (built next) | Runs on | Dev routing |
|---|---|---|---|---|
| **View data** (board, crew, alerts, sidebar) | `HttpApiService` → `GET/POST /api/v1/…` | **`api/app.py`** (Flask) over **`core/`** — Gayathri + Kashifa. Endpoints = `docs/REST_API_v1.md` | `:5000` | `proxy.conf.json` sends `/api/*` → `:5000` |
| **Advisor** (chat bubble only) | `AdvisorService` → `POST /api/v1/ask` (SSE) | same Flask app, agent route — Shashank | `:5000` | same proxy |

Today both are faked **inside the browser** (`MockApiService`, `MockAdvisorService`) so nothing external is needed. `api/mock.py` is a throwaway reference emitter — the frontend does not use it.

**The swap for tomorrow:** `src/environments/environment.ts` → `useMock: false`. One line. No component changes.

---

## 1. Boot sequence

```
main.ts
  └─ bootstrapApplication(AppComponent, appConfig)
       └─ app.config.ts providers, in order:
            1. provideZoneChangeDetection({ eventCoalescing: true })
            2. provideHttpClient(withFetch())          ← HttpApiService needs this
            3. provideRouter(routes)                    ← app.routes.ts
            4. { provide: API, useClass:                ← THE SWAP POINT
                   environment.useMock ? MockApiService : HttpApiService }
            5. provideAppInitializer(() =>
                 environment.useMock ? inject(Dataset).load() : Promise.resolve())
                 └─ mock mode: fetch src/assets/data/*.json, build in-memory indexes,
                    THEN the app is allowed to render. Real mode: no-op.
  └─ AppComponent  →  <app-cockpit />
```

So by the time any component runs, `API` is bound to one implementation and (in mock mode) the dataset is loaded.

---

## 2. One request, start to finish

Example: user changes the date picker; the flights board reloads.

```
CockpitComponent date <select> (change)
  → AppState.setDate("2026-09-15")
      → this.date  (signal)  set

BoardComponent has:  effect(() => { const d = this.state.date(); this.api.flights({date:d}).subscribe(...) })
  → the signal read inside effect() means the effect RE-RUNS on every date change
      → this.api.flights({date:"2026-09-15"})
          this.api === whatever DI gave for the API token
          ├─ mock mode → MockApiService.flights()
          │     → reads Dataset.flights, filters to the date,
          │       maps each through derive.toFlightRow() (computes delay_rank),
          │       sorts by delay_rank_score,
          │       returns of(rows).pipe(delay(70))     ← fake latency
          └─ real mode → HttpApiService.flights()
                → this.http.get('/api/v1/flights?date=2026-09-15')
                → dev server proxies to  http://localhost:5000/api/v1/flights?date=…
                → Flask api/app.py  →  core/  →  JSON  →  Observable
  → .subscribe(rows => this.all.set(rows))   ← result dropped into a signal
      → computed rows() re-derives (applies the rank filter)
      → template @for re-renders the table
```

**Every screen is this same shape:** `effect(read AppState.date) → api.<method>() → .subscribe(x => signal.set(x)) → template`.

Nothing calls `fetch`/`HttpClient` except `HttpApiService`. Components only know the `API` token.

---

## 3. The files, in dependency order

### Core / data layer — `src/app/core/`

| File | What it is |
|---|---|
| **`api.types.ts`** | Every REST DTO — `FlightRow`, `FlightDetail`, `CrewRow`, `CrewDetail`, `Alert`, `Summary`, `Option`, `RuleVerdict`, `CandidateResult`, … Shared by mock and real so shapes can't drift. |
| **`api.port.ts`** | `ApiPort` — the interface listing all 36 methods (`flights`, `flight`, `downstream`, `pairing`, `candidates`, `crew`, `crewDetail`, `crewLegality`, `dutyClock`, `reserves`, `alerts`, `ackAlert`, `resolveAlert`, `summary`, `riskSignals`, `meta`, `rules`, `stations`, `aircraft`, `costs`, `postDecision`, `getDecisions`). And `export const API = new InjectionToken<ApiPort>('API')` — **this is what components inject.** |
| **`http-api.service.ts`** | `HttpApiService implements ApiPort`. Each method is a one-liner `this.http.get<T>('${base}/…', {params})`. `base = environment.apiBase + '/api/v1'`. This is the real transport. |
| **`app-state.ts`** | `AppState` — `date` signal (the working day) + `meta` signal (week bounds for the date picker). `init()` calls `api.meta()` once. Every view reads `state.date()`. |
| **`mock/dataset.ts`** | `Dataset` — `load()` fetches the 10 bundled JSON files from `assets/data/`, builds Maps (`crewById`, `flightById`, `pairingById`, `dutyById`, `certsByCrew`, `pairingsByCrew`, …). The in-browser equivalent of `core/World`. |
| **`mock/derive.ts`** | Pure functions — the mock's "business logic": `delayRank()` (the board colour formula), `toFlightRow()`, `attention()` (needs-attention reasons), `certRows()` (days-to-expiry), `onDuty()`, `toCrewRow()`, `buildAlerts()` (the HITL scan), `buildSummary()` (sidebar counts), `coverCandidates()` (reserve-pool shortlist + funnel), `legalityVerdicts()` (lightweight 7-rule check), `reserveRows()`. **These mirror what `core/` must do — Kashifa can read them as a spec.** |
| **`mock/mock-api.service.ts`** | `MockApiService implements ApiPort`. Each method = pull rows from `Dataset` + run `derive` fns + `return of(result).pipe(delay(70))`. Also holds ephemeral state: `alertState` (ack/resolve), `decisions[]`. |

### App wiring — `src/app/`

| File | What it is |
|---|---|
| **`main.ts`** | `bootstrapApplication(AppComponent, appConfig)`. |
| **`app.config.ts`** | The providers list in §1. The `{ provide: API, useClass: … }` line is the whole mock↔real switch. |
| **`app.routes.ts`** | `'' → /board`, `/board` (lazy `BoardComponent`), `/crew` + `/crew/:id` (lazy `CrewComponent`), `** → /board`. |
| **`app.component.ts`** | Just `<app-cockpit />`. |

### Shell — `src/app/shell/`

| File | What it does |
|---|---|
| **`cockpit.component.ts`** | The frame. Topbar: brand, **nav** (`/board` \| `/crew` via `routerLink`), **date `<select>`** (bound to `AppState.date`), **MOCK/LIVE chip** (`environment.useMock`). Body: 3-column grid — `<app-sidebar>` (left) │ `<router-outlet>` (center) │ `<app-alerts-panel>` (right). Plus `<app-chat-bubble>` floating. `ngOnInit → AppState.init()`. |

### Feature: sidebar — `src/app/features/sidebar/`

| File | What it does |
|---|---|
| **`sidebar.component.ts`** | `inject(API)`, `inject(AppState)`. `effect(() => api.summary(state.date()).subscribe(s => this.summary.set(s)))` — reloads on date change. `api.riskSignals(0.5)` once for the watch-list. Renders: 4 crew tiles (each `routerLink="/crew"` with `queryParams` filter), flight risk mix (at-risk / elevated / nominal / total), reserve pool by `base·role` (low ones highlighted), disruption watch-list (each row `routerLink="/crew/{id}"`). |

### Feature: alerts — `src/app/features/alerts/`

| File | What it does |
|---|---|
| **`alerts-panel.component.ts`** | `inject(API, AppState, AdvisorBus, Router)`. `effect → api.alerts(date, 'open')`. Per alert card: type, severity, title, detail, and actions — **"Ask the advisor"** → `bus.ask(ask_prompt)` (opens the bubble with a question); **deep-link** → `router.navigateByUrl('/crew/C-xxxx' or '/board?flight=…')`; **Ack** → `api.ackAlert(id)`; **Resolve** → `api.resolveAlert(id)`. Header shows critical/warning counts. |

### Feature: board (main display) — `src/app/features/board/`

| File | What it does |
|---|---|
| **`board.component.ts`** | `inject(API, AppState, AdvisorBus, ActivatedRoute)`. `effect → api.flights({date})` → `all` signal; `rows()` computed applies the rank-filter pills (`critical/high/medium/low`). Table: coloured left-border + dot per `delay_rank`, flight no, route, dep–arr UTC, tail, **slack minutes** (red if <45), downstream count. Row click → `select(f)`: `api.flight(id)` (drawer: operating crew + per-crew duty pressure), `api.downstream(id, 90)` (tail legs with cumulative +90m delay; same-pairing legs flagged amber), `api.candidates(pairing, 'Captain', dep_utc)` (reserve-pool cover options). "Ask the advisor to resolve" → `bus.ask(...)`. Reads `?flight=` query param to auto-open (from an alert deep-link). |

### Feature: crew — `src/app/features/crew/`

| File | What it does |
|---|---|
| **`crew.component.ts`** | `inject(API, AppState, AdvisorBus, ActivatedRoute, Router)`. Three effects: (a) `?filter=` query param → `filter` signal; (b) `:id` route param → `select(id)`; (c) `[date, filter, role, q]` → `api.crew({...})` → `rows`. Filter pills (`needs_attention` default / `on_duty` / `off_duty` / `on_reserve` / `all`), role `<select>`, id/name search. Row → coloured if `attention.flag`, duty-7d, risk. Click → `select(id)` → `api.crewDetail(id, date)` → drawer: attention reasons, **duty clock** (7d/28d + headroom, rest OK), **certifications** (valid-to + days-to-expiry, red if lapsed), risk drivers, this-week assignments — click an assignment → `api.crewLegality(crewId, pairingId)` → **live 7-rule verdict list**. "Ask the advisor about C-xxxx" → `bus.ask(...)`. |

### Feature: advisor (the chat bubble) — `src/app/features/advisor/`

| File | What it does |
|---|---|
| **`advisor-bus.ts`** | `AdvisorBus` — tiny signal service. `open` (bubble expanded?), `pending` (a queued question). `ask(prompt)` sets both; `consume()` reads+clears `pending`; `toggle()`. This is how the board/crew/alert views inject questions into the chat. |
| **`chat-bubble.component.ts`** | `inject(AdvisorBus, ConversationStore)`. Collapsed = a FAB ("💬 Ask the advisor"). Expanded = a panel: `<app-conversation>` (the thread) + `<app-chat-composer>` (input) + `<app-evidence-rail>` (funnel / rule-trace / blast-radius / policy sliders). `effect(() => { if (bus.open() && bus.pending()) store.ask(bus.consume()) })` — a question pushed from anywhere runs here. |

### Advisor SSE machinery (pre-existing, reused unchanged) — `src/app/services/` + `src/app/components/`

| File | What it does |
|---|---|
| **`models/agent-events.ts`** | The `AgentEvent` union (`status \| tool_call \| tool_result \| rule_check \| token \| answer \| abstain \| done \| error`) + the `AssistantTurn` view model. This is the **advisor** contract (separate from the REST `ApiPort`). |
| **`services/advisor.service.ts`** | `AdvisorService.ask()` — mock mode → `MockAdvisorService`; real mode → `POST /api/v1/ask` read as a `fetch()` stream, frames split on `\n\n`, each `data:` line parsed to an `AgentEvent`. Returns `Observable<AgentEvent>`. |
| **`services/mock-advisor.service.ts`** | Scripted `[delayMs, AgentEvent][]` sequences for Tier 1 / Tier 2 / Tier 3 / abstain, keyed by keywords in the question. |
| **`services/turn-reducer.ts`** | `reduceTurn(turn, event)` — pure. Folds one event into the `AssistantTurn` (append trace step, add rule check, append prose token, attach answer, mark done…). |
| **`services/conversation.store.ts`** | `ConversationStore` — `turns` signal, `busy`, `weights`. `ask(q)` → pushes a user turn + empty assistant turn → `advisor.ask(q).pipe(scan(reduceTurn)).subscribe(t => replace(turnId, t))`. Progressive re-render as events stream. |
| **`services/scenarios.service.ts`** | `/scenarios` list + `/rank` (policy-slider re-rank) with local fallbacks; `SEEDED_ASKS` for the empty state. |
| **`components/conversation.component.ts`** | Empty state (seeded-ask buttons) or the thread — maps each turn to a user bubble or `<app-assistant-turn>`. |
| **`components/chat-composer.component.ts`** | Textarea → `store.ask()`. |
| **`components/assistant-turn.component.ts`** | Renders one assistant turn in the load-bearing order: **answer card → rule-trace → reasoning trail → prose last**. Picks `tier1-table` / `impact-card` / `options-card` / `abstain-card` by `answer.kind`. |
| **`components/{tier1-table,impact-card,options-card,funnel,rule-trace,rule-chip,blast-radius,policy-sliders,trace-panel,abstain-card}.component.ts`** | Leaf presentational cards for the advisor answers. |
| **`components/evidence-rail.component.ts`** | Pulls `funnel` / `ruleChecks` / `blast_radius` / `options` off `ConversationStore.lastAssistant()`; policy sliders → `scenarios.rank()` → live re-ordered list. |

---

## 4. Where each screen's data comes from

| Screen element | `API` method(s) | Real endpoint |
|---|---|---|
| Date picker | `meta()` | `GET /api/v1/meta` |
| Sidebar | `summary(date)`, `riskSignals(0.5)` | `GET /summary`, `/risk-signals` |
| Alerts panel | `alerts(date,'open')`, `ackAlert`, `resolveAlert` | `GET /alerts`, `POST /alerts/{id}/ack`, `/resolve` |
| Flights board | `flights({date})` | `GET /flights?date=` |
| Flight drawer | `flight(id)`, `downstream(id,90)`, `candidates(pairing,role,dep_utc)` | `GET /flights/{id}`, `/flights/{id}/downstream`, `/pairings/{id}/candidates` |
| Crew list | `crew({date,filter,role,q})` | `GET /crew` |
| Crew drawer | `crewDetail(id,date)`, `crewLegality(id,pairing)` | `GET /crew/{id}`, `/crew/{id}/legality` |
| Chat bubble | `AdvisorService.ask()` (SSE) | `POST /api/v1/ask` |

---

## 5. Tomorrow's cutover

1. Gayathri's `api/app.py` serves the endpoints above on `:5000`.
2. `src/environments/environment.ts` → `useMock: false`.
3. `npm start`. The dev server proxies `/api` → `:5000`; `HttpApiService` is now the `API` implementation; `Dataset.load()` is skipped.
4. Components, templates, signals — untouched.
