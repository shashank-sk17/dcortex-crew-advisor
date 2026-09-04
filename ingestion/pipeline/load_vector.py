"""Embed + upsert into the 4 pgvector collections. `db.connect()` already
called `register_vector()`, so a plain Python list of floats can be passed
directly as a `vector` column parameter.
"""
from __future__ import annotations

import json

import psycopg

from . import transform_vector as tv
from .db import register_vector_type
from .embeddings import Embedder
from .loaders import Dataset


def load_rules(conn: psycopg.Connection, ds: Dataset, embedder: Embedder) -> int:
    records = tv.rule_records(ds)
    vectors = embedder.embed([r["embed_text"] for r in records])
    sql = """
        INSERT INTO rules_vec (rule_id, text, params, embed_text, embedding)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (rule_id) DO UPDATE SET
            text = EXCLUDED.text, params = EXCLUDED.params,
            embed_text = EXCLUDED.embed_text, embedding = EXCLUDED.embedding
    """
    rows = [
        (r["rule_id"], r["text"], json.dumps(r["params"]), r["embed_text"], vec)
        for r, vec in zip(records, vectors)
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def load_scenario_precedent(conn: psycopg.Connection, ds: Dataset, embedder: Embedder) -> int:
    records = tv.scenario_precedent_records(ds)
    vectors = embedder.embed([r["embed_text"] for r in records])
    sql = """
        INSERT INTO scenario_precedent_vec (scenario_id, difficulty, event_type, answer_key, embed_text, embedding)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (scenario_id) DO UPDATE SET
            difficulty = EXCLUDED.difficulty, event_type = EXCLUDED.event_type,
            answer_key = EXCLUDED.answer_key, embed_text = EXCLUDED.embed_text,
            embedding = EXCLUDED.embedding
    """
    rows = [
        (
            r["scenario_id"],
            r["difficulty"],
            r["event_type"],
            json.dumps(r["answer_key"]),
            r["embed_text"],
            vec,
        )
        for r, vec in zip(records, vectors)
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def load_controller_notes(conn: psycopg.Connection, ds: Dataset, embedder: Embedder) -> int:
    records = tv.controller_note_records(ds)
    vectors = embedder.embed([r["note"] for r in records])
    sql = """
        INSERT INTO controller_note_vec (crew_id, date, rule, note, embedding)
        VALUES (%s, %s, %s, %s, %s)
    """
    # No natural unique key beyond the surrogate id -- flagged_exceptions is
    # tiny and re-running against an unchanged dataset would only matter if
    # we needed exact dedup; truncate-and-reload semantics for this one table
    # are handled by run_ingestion.py's --reset flag instead of ON CONFLICT.
    rows = [
        (r["crew_id"], r["date"], r["rule"], r["note"], vec)
        for r, vec in zip(records, vectors)
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def load_intent_examples(conn: psycopg.Connection, ds: Dataset, embedder: Embedder) -> int:
    records = tv.intent_example_records(ds)
    vectors = embedder.embed([r["embed_text"] for r in records])
    sql = """
        INSERT INTO intent_example_vec (question_id, tier, rules_ref, prompt, embed_text, embedding)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (question_id) DO UPDATE SET
            tier = EXCLUDED.tier, rules_ref = EXCLUDED.rules_ref,
            prompt = EXCLUDED.prompt, embed_text = EXCLUDED.embed_text,
            embedding = EXCLUDED.embedding
    """
    rows = [
        (r["question_id"], r["tier"], r["rules_ref"], r["prompt"], r["embed_text"], vec)
        for r, vec in zip(records, vectors)
    ]
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
    return len(rows)


def load_all(
    conn: psycopg.Connection, ds: Dataset, embedder: Embedder, reset_notes: bool = False
) -> dict[str, int]:
    counts: dict[str, int] = {}
    register_vector_type(conn)  # idempotent; needed if --vector runs without --schema this invocation
    if reset_notes:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE controller_note_vec RESTART IDENTITY")
    counts["rules_vec"] = load_rules(conn, ds, embedder)
    counts["scenario_precedent_vec"] = load_scenario_precedent(conn, ds, embedder)
    counts["controller_note_vec"] = load_controller_notes(conn, ds, embedder)
    counts["intent_example_vec"] = load_intent_examples(conn, ds, embedder)
    conn.commit()
    return counts
