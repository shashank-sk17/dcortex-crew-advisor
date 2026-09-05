# Ops Console (L4) — Angular 19

A live crew-control cockpit. **Fully working today with zero backend** — the
dataset is bundled into the app and every REST response is computed in-browser.
Tomorrow: flip one flag, the same components hit Gayathri's real endpoints.

```bash
npm install
npm start            # http://localhost:4200  — works standalone, no backend
```

## The rule: components never call HTTP

```
 component  ──▶  inject(API)  ──▶  { provide: API, useClass: … }   ← app.config.ts
                                     │
                    environment.useMock ? MockApiService : HttpApiService
                                     │
        MockApiService: computes from src/assets/data/*.json (the real dataset)
        HttpApiService: GET/POST /api/v1/…  (docs/REST_API_v1.md)
```

- Every component / feature store injects **`API`** (the token in `core/api.port.ts`) and calls e.g. `api.flights({ date })`. It never knows which implementation it got.
- `MockApiService` and `HttpApiService` both `implements ApiPort` — identical signatures. The compiler enforces they stay in sync.
- **The entire mock → real integration step:** `src/environments/environment.ts` → `useMock: false`. No component, store, or template changes. (Prod builds already set it via `fileReplacements`.)

## Layout

```
core/
  api.types.ts        every REST DTO (FlightRow, CrewDetail, Alert, Summary, …)
  api.port.ts         ApiPort interface + the API injection token
  http-api.service.ts real transport — HttpClient, paths = docs/REST_API_v1.md
  mock/
    dataset.ts        loads src/assets/data/*.json once at startup (APP_INITIALIZER)
    derive.ts         delay_rank formula, attention flags, alerts, summary, candidates, legality
    mock-api.service.ts  every endpoint, computed from the dataset in memory
  app-state.ts        the working `date` signal (drives every view)

shell/cockpit.component.ts     topbar (nav + date picker) · left sidebar · center outlet · right alerts · chat bubble
features/
  board/       daily flights list, colour-coded by delay_rank; row → detail drawer
               (operating crew, downstream tail cascade, reserve-pool cover options)
  crew/        list + filters (needs-attention / on-duty / off-duty / on-reserve / role)
               row → detail drawer (duty clock, certs w/ expiry, per-pairing 7-rule legality)
  alerts/      HITL panel — DUTY_LIMIT_NEAR · CERT_EXPIRING · FLIGHT_AT_RISK · RESERVE_POOL_LOW
               · ROSTER_EXCEPTION; ack / resolve; "Ask the advisor" deep-links into the bubble
  sidebar/     one /summary call — crew counts, flight risk mix, reserve pool, disruption watch-list
  advisor/     chat bubble (bottom-right). Wraps the SSE advisor stream + Tier 1/2/3 + abstain
               cards + evidence rail. AdvisorBus lets any view push a question in.
```

## Two backends, deliberately separate

| | Transport | Serves | Today | Tomorrow |
|---|---|---|---|---|
| **View data** | REST (`ApiPort`) | board, crew, alerts, sidebar | `MockApiService` (in-app, real dataset) | `api/app.py` over `core/` |
| **Advisor** | SSE (`AdvisorService`) | the chat bubble only | scripted `MockAdvisorService` | `POST /api/v1/ask` |

Both switch on `environment.useMock`.

## delay_rank (the board's colour)

Computed in `core/mock/derive.ts::delayRank` — critical / high / medium / low from
tail slack, operating-crew FDP headroom, downstream leg count, and whether the
pairing overnights away from base. Same formula the backend should implement
(spelled out in `docs/REST_API_v1.md` §2).
