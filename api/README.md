# api/

FastAPI implementation of `Crew_Operations_Advisor_REST_API_v2.pdf` — all 19
endpoints, backed by the already-ingested Postgres+pgvector database (see
`../ingestion/`). Standalone from `ingestion/` by design — no imports either
direction, per `ingestion/README.md`'s stated boundary.

## Quickstart

```bash
cd api
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # set DATABASE_URL to your Neon connection string
uvicorn main:app --reload --port 8000
```

Then `GET http://localhost:8000/api/v1/crew` etc., or see the auto-generated
docs at `http://localhost:8000/docs`.

## Layout

```
api/
├── pii.py        PII/sensitive-data redaction layer -- every response model
│                 inherits PIISafeModel, which redacts email, phone, Aadhaar,
│                 PAN, passport, payment-card (Luhn-checked), and IP patterns
│                 automatically, plus unconditionally masks any field typed
│                 `Address` or named like one of the DPDP/SPDI sensitive
│                 categories (address, DOB, health notes, bank details,
│                 government IDs, emergency contact). No such fields exist in
│                 the dataset today; this is defense-in-depth for when they
│                 get added. Deliberately does NOT redact crew name/rank/
│                 base/crew_id -- those are operationally necessary (a
│                 controller must know who to call).
├── schemas.py    Pydantic models matching the PDF spec's field names/nesting
│                 verbatim -- this is the frozen frontend contract.
├── db.py         Postgres connection (separate from ingestion/pipeline/db.py)
├── queries.py    Data access layer -- one function per query. All rule
│                 thresholds (60h/7d, 100h/28d, 12h rest) are read from
│                 `rules_vec` at query time, never hardcoded.
├── advisory.py   Business logic for POST /advisory (the main decision endpoint)
├── main.py       FastAPI routes wiring it all together
└── tests/
    └── test_endpoints_live.py   runs against a real database (DATABASE_URL),
                                  not mocked -- see the file's docstring for
                                  why: several real bugs were only catchable
                                  this way (see "Bugs found" below).
```

## Two known simplifications (disclosed, not hidden)

1. **`checks.duty_limits_ok` uses current accrued hours, not a prospective
   what-if.** `/legality`, `/candidates`, and `/advisory` check
   `duty_hours_7d`/`flight_hours_28d` as they stand today, not what they'd
   become *after* adding this specific new assignment. Full calendar-window
   simulation for a hypothetical new duty belongs in `core/LEX` (not yet
   built), not this REST layer. In practice this means a candidate can come
   back "eligible" here while a full LEX check would catch a prospective
   breach — verified directly: C-2087 in the S2 scenario is correctly
   flagged ineligible by this API, but via a real independent RULE-REST-04
   violation (4h rest against a 12h minimum) rather than the RULE-DUTY-02
   breach the answer key cites. Both are true; this layer just doesn't
   compute the second one.
2. **`score` in `/candidates` and `/advisory` is a simple heuristic**
   (eligibility + which checks passed + seniority), not JUDGE's exact
   cost-optimal ranking (`core/judge.py`, not yet built). Final candidate
   *ordering* is cost-first regardless, matching the project's documented
   `(legal, cost, delay)` ranking principle — but the `score` field itself
   is illustrative, not authoritative.

## Bugs found and fixed while building this (kept as regression tests)

Real, verified issues caught by testing against the live database rather
than trusting the code — see `tests/test_endpoints_live.py` for the
regression test guarding each one:

1. **PII regex false-positived on ISO dates.** The phone-number pattern
   matched date-shaped digit-hyphen sequences (`2026-09-15` looked
   phone-like), corrupting every date/timestamp/flight-ID field in every
   response. Fixed by requiring a leading `+`/parens or an unbroken 7-15
   digit run — see `pii.py`'s comment for the reasoning.
2. **`RULE-CERT-06` was implemented as a two-sided range check**
   (`valid_from <= date <= valid_to`), which fails for **100% of crew**
   because `certifications.json`'s `licence` row has a `valid_from` in the
   future for every single crew member — a `generate.py` artifact
   (`exp - 730 days` where `licence`'s expiry window starts past 730 days
   out), not an engineered test case. The dataset's own internal consistency
   check (`certs_ok()` in `generate.py`) only checks `valid_to`. Fixed to
   match; also corrected `docs/RULES.md`, which documented the wrong
   (two-sided) version.
3. **`/advisory` recommended the affected/sick crew member to cover their
   own pairing.** The candidate pool didn't exclude `affected_crew.crew_id`.
4. **`/advisory` crashed with a `str`/`date` comparison `TypeError`** because
   the request was dumped in JSON mode (dates become strings) before
   reaching functions that compare against native `date` objects from
   Postgres.
5. **Candidate ranking let a heuristic score override cost** — a senior
   captain on a ₹24,000 day-off callout could outrank a cheaper ₹18,500
   reserve at equal eligibility. Fixed to sort by `(eligible, cost, score)`,
   matching the project's own documented ranking principle. Confirmed fix:
   `/advisory` against the S2 scenario now recommends exactly the answer
   key's #1 pick — Captain C-3310, reserve callout, ₹18,500.
6. **`/candidates` and `/advisory` took 97 seconds for 25 candidates** —
   the official problem statement explicitly says a 45-second response
   "is not a decision aid." Root cause was two stacked problems, not one:
   - `db.py` opened a brand-new TCP/TLS connection to Neon *per query*
     instead of reusing one. Fixed with a real connection pool
     (`psycopg_pool.ConnectionPool`). That alone cut it to 30s.
   - `compute_legality()` was called once per candidate, each call issuing
     ~7 sequential queries — a classic N+1 pattern, and pooling only removes
     connection overhead, not the round-trip count. Fixed by adding
     `compute_legality_bulk()`, which fetches crew/certs/duty-clocks/roster-
     exceptions for *all* candidates in ~6 queries total (not 7×N), plus the
     pairing/rule facts that don't vary per candidate (previously re-fetched
     for every single candidate for no reason).
   - Result: 97s → 1.15s for 25 candidates, 142 candidates (no filter at
     all) in under a second, `/advisory` in ~4s. The full pytest suite went
     from 12 minutes to 5.8 seconds.
7. **PII redaction only checked field names at the top level of a response.**
   A sensitive field name buried inside a nested list (e.g. inside
   `PairingDetail.days[]`) was never checked at all -- only a model's own
   direct fields were. Fixed by making the recursive path field-name-aware
   too, not just the top level.
8. **`Optional[Address]` and `list[Address]` fields leaked completely
   unredacted.** The sensitivity check was `annotation is Address`, an exact
   identity comparison -- `Address` wrapped in `Union[Address, None]` or
   `list[Address]` is never `is Address` itself, so both leaked 100% of the
   time. Fixed by unwrapping generic type args recursively.
9. **A 16-digit number that failed its Luhn check (so wasn't redacted as a
   card) had its first 12 digits then mis-matched as an Aadhaar number.**
   The Aadhaar pattern didn't check whether it was actually a fragment of a
   longer 4-group sequence. Fixed with an explicit boundary guard.
10. **`Address(str)` as a bare subclass couldn't even be used as a Pydantic
    v2 field type** -- it raised `PydanticSchemaGenerationError` at model
    *definition* time, before ever reaching redaction logic. Fixed by
    implementing `__get_pydantic_core_schema__` so Pydantic treats it as a
    plain `str` for validation.
