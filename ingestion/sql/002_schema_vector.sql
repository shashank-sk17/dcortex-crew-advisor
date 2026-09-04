-- 002_schema_vector.sql
-- Semantic retrieval over rules, precedent, and narrative. See
-- docs/DATA_STORAGE_DESIGN.md §3/§3a for what goes here and what deliberately
-- doesn't (LEX-computed rule-verdict text is never embedded -- see §3a).
--
-- Embedding model: BAAI/bge-small-en-v1.5 (fastembed, local, no API key) --
-- 384 dimensions. If the embedding provider changes, this dimension MUST
-- change to match (pipeline/config.py:EMBEDDING_DIM is the single source of
-- truth the ingestion code reads from -- keep it in sync with this file).
--
-- Hybrid search = BM25 half (native Postgres full-text via the `search_tsv`
-- generated column + GIN index) + semantic half (pgvector cosine via the
-- `embedding` column + HNSW index), combined at query time with your own
-- 0.5/0.5 weights. One query, one database, per docs/DATA_STORAGE_DESIGN.md §4.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- rules
CREATE TABLE IF NOT EXISTS rules_vec (
    rule_id     TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    params      JSONB NOT NULL DEFAULT '{}',
    embed_text  TEXT NOT NULL,           -- exact text the embedding was computed from
    embedding   vector(384) NOT NULL,
    search_tsv  TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', embed_text)) STORED
);
CREATE INDEX IF NOT EXISTS idx_rules_vec_search_tsv ON rules_vec USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS idx_rules_vec_embedding ON rules_vec USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------- scenario precedent
-- S1-S6 only. internal/held_out_scenarios.json (H1, H2) is deliberately NEVER
-- ingested here -- DECISIONS.md #8 locks it as an untuned honest self-check,
-- and the only way to guarantee it never leaks into a controller-facing
-- semantic search result is to never put it in the retrievable store at all.
-- The eval harness reads H1/H2 straight from that JSON file at T+21, no DB
-- involved.
CREATE TABLE IF NOT EXISTS scenario_precedent_vec (
    scenario_id     TEXT PRIMARY KEY,
    difficulty      TEXT,
    event_type      TEXT NOT NULL,
    answer_key      JSONB NOT NULL,        -- structured payload: retrieved, never searched
    embed_text      TEXT NOT NULL,         -- narrative + options[].reasoning + expected_choice.reasoning + answer_key.note, concatenated
    embedding       vector(384) NOT NULL,
    search_tsv      TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', embed_text)) STORED
);
CREATE INDEX IF NOT EXISTS idx_scenario_precedent_search_tsv ON scenario_precedent_vec USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS idx_scenario_precedent_embedding ON scenario_precedent_vec USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------- controller notes
CREATE TABLE IF NOT EXISTS controller_note_vec (
    id          BIGSERIAL PRIMARY KEY,
    crew_id     TEXT,
    date        DATE,
    rule        TEXT,
    note        TEXT NOT NULL,
    embedding   vector(384) NOT NULL,
    search_tsv  TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', note)) STORED
);
CREATE INDEX IF NOT EXISTS idx_controller_note_search_tsv ON controller_note_vec USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS idx_controller_note_embedding ON controller_note_vec USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_controller_note_crew ON controller_note_vec (crew_id);

-- ---------------------------------------------------------------- intent examples (router few-shot corpus)
CREATE TABLE IF NOT EXISTS intent_example_vec (
    question_id     TEXT PRIMARY KEY,
    tier            INTEGER NOT NULL,
    rules_ref       TEXT[] NOT NULL DEFAULT '{}',
    prompt          TEXT NOT NULL,
    embed_text      TEXT NOT NULL,     -- prompt + explanation + expected_answer.reasoning (where present)
    embedding       vector(384) NOT NULL,
    search_tsv      TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', embed_text)) STORED
);
CREATE INDEX IF NOT EXISTS idx_intent_example_search_tsv ON intent_example_vec USING GIN (search_tsv);
CREATE INDEX IF NOT EXISTS idx_intent_example_embedding ON intent_example_vec USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_intent_example_tier ON intent_example_vec (tier);

COMMIT;
