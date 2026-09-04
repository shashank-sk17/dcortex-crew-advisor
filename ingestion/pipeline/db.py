"""Postgres connection + schema application. psycopg3, sync (this pipeline is
a batch job, not a request-serving path -- no need for async here)."""
from __future__ import annotations

import psycopg
from pgvector.psycopg import register_vector

from . import config


def connect(settings: config.Settings) -> psycopg.Connection:
    return psycopg.connect(settings.database_url, autocommit=False, prepare_threshold=None)


def register_vector_type(conn: psycopg.Connection) -> None:
    register_vector(conn)


def apply_schema(conn: psycopg.Connection) -> None:
    """Applies both DDL files, in order. Idempotent -- every statement in
    them is CREATE ... IF NOT EXISTS / CREATE EXTENSION IF NOT EXISTS."""
    for filename in ("001_schema_postgres.sql", "002_schema_vector.sql"):
        sql = (config.SQL_DIR / filename).read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute(sql)
    conn.commit()
    register_vector_type(conn)  # `vector` type now exists in the catalog -- safe to register
