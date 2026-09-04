# ingestion/

Ingests the vendored dataset (`../crew-ops-advisor-dataset/data/*.json`) into
PostgreSQL (structured tables) and pgvector (semantic collections, same
Postgres instance). Design rationale: [`../docs/DATA_STORAGE_DESIGN.md`](../docs/DATA_STORAGE_DESIGN.md).
Test-set spec this pipeline's output should satisfy: [`../docs/TEST_SETS.md`](../docs/TEST_SETS.md).

This folder is standalone — it never imports from `core/`/`api/`/`agent/` and
nothing there imports from it. It only reads `../crew-ops-advisor-dataset/`
(never writes to it) and writes to Postgres.

---

## 1. Quickstart

```bash
cd ingestion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # defaults already match docker-compose.yml
docker compose up -d        # pgvector/pgvector:pg16, exposed on localhost:5433
                             # wait for it to report healthy: docker compose ps

python run_ingestion.py --all
```

Expected output ends with a per-table row-count validation, all `OK`:

```
Validating row counts against source JSON ...
  crew                     expected=150   actual=150   OK
  flights                  expected=147   actual=147   OK
  ...
All row counts match.
Done.
```

## 2. What actually got tested, and what didn't

**No live Postgres was reachable in the environment this was built in**
(Docker required elevated group membership not available there). Everything
that *can* be verified without a live database was:

- Every transform function (`pipeline/transform_postgres.py`,
  `pipeline/transform_vector.py`) run against the real vendored dataset —
  `tests/test_transforms_dry_run.py`, 28 tests, all passing. This includes
  referential-integrity checks (every `flight_id`/`crew_id` a join table
  points to actually exists in the source data) run in Python *before* they'd
  ever hit a Postgres foreign key.
- Both DDL files (`sql/001_schema_postgres.sql`, `sql/002_schema_vector.sql`)
  parsed against real Postgres grammar via `pglast` (libpg_query bindings —
  the actual Postgres parser, not a guess).
- The local embedder (`fastembed`, `BAAI/bge-small-en-v1.5`) actually
  downloaded its model and produced real 384-dim vectors — not mocked.

**Not yet run against a live database**: the actual `INSERT`/`ON CONFLICT`
statements, the FK constraints as enforced by Postgres itself, the HNSW/GIN
indices, and end-to-end `run_ingestion.py --all`. Run the Quickstart above
once you have Docker access to close that gap — the row-count validator
(`--validate`) is exactly the check to run first.

## 3. Layout

```
ingestion/
├── sql/
│   ├── 001_schema_postgres.sql   structured tables + indices
│   └── 002_schema_vector.sql     pgvector extension, 4 vector tables + HNSW/GIN indices
├── pipeline/
│   ├── config.py                  env-driven settings (DATABASE_URL, EMBEDDING_PROVIDER, ...)
│   ├── loaders.py                 reads the 12 vendored JSON files
│   ├── transform_postgres.py      JSON -> row tuples, one function per table
│   ├── transform_vector.py        JSON -> {id, embed_text, metadata}, one function per collection
│   ├── embeddings.py               pluggable embedder: local (fastembed, default) | openai
│   ├── db.py                       connection + idempotent schema apply
│   ├── load_postgres.py            upserts (ON CONFLICT DO UPDATE) into every structured table
│   ├── load_vector.py              embeds + upserts into every vector table
│   └── validate.py                 row-count check, expected counts derived from the dataset itself
├── tests/
│   └── test_transforms_dry_run.py  28 tests, zero DB dependency — see §2
├── run_ingestion.py                 CLI entrypoint
├── docker-compose.yml                pgvector/pgvector:pg16, port 5433
├── requirements.txt
└── .env.example
```

## 4. Design decisions worth knowing before you touch this

- **Idempotent by default.** Every Postgres/vector load is `INSERT ... ON
  CONFLICT ... DO UPDATE`, so re-running `--all` against an unchanged dataset
  is a no-op in effect. The one exception is `controller_note_vec` (no
  natural unique key on a free-text note) — pass `--reset-notes` to truncate
  it first if you're re-running repeatedly during development.
- **`internal/held_out_scenarios.json` (H1, H2) is never ingested anywhere.**
  `DECISIONS.md` #8 locks the held-out set as an untuned honest self-check;
  the only way to guarantee it can never leak into a controller-facing
  semantic search result is to never put it in the retrievable store. See the
  comment above `scenario_precedent_vec` in `sql/002_schema_vector.sql`, and
  `test_scenario_precedent_excludes_held_out` in the test suite.
- **LEX-computed rule-verdict text is never embedded.** `excluded_candidates[].reason`
  and friends are deterministic tool output, not narrative precedent —
  embedding them risks the agent retrieving a stale/mismatched verdict
  instead of computing a fresh one, which is exactly what the project's trust
  boundary (README §2, "the LLM never calculates") exists to prevent. Full
  reasoning in `docs/DATA_STORAGE_DESIGN.md` §3a.
- **Embedding dimension is 384, fixed by `config.EMBEDDING_DIM`.** Every
  `vector(384)` column in `002_schema_vector.sql` must match it. If you
  switch embedding model/provider, update both together — `embeddings.py`
  raises loudly (`_assert_dim`) if a provider ever returns a mismatched
  dimension, rather than silently corrupting the column.
- **This is a proposal-stage pipeline, not yet wired into `core/`/`api/`.**
  `DECISIONS.md` #1 ("no database") hasn't been formally superseded — see
  `docs/DATA_STORAGE_DESIGN.md` §6. Nothing in `core/`/`api/`/`agent/` reads
  from this database yet; that's the next integration step once the team
  finalizes the storage-architecture decision.

## 5. Re-running against a changed dataset

`crew-ops-advisor-dataset/` is vendored and should never be hand-edited (see
`docs/SETUP.md`). If it's ever regenerated via its own `generate.py` (e.g. a
newer dataset version), just re-run `python run_ingestion.py --all` — schema
application and every load are idempotent, and `validate.py`'s expected
counts are computed from the dataset in memory, not hardcoded, so they'll
still be correct against the new sizes.
