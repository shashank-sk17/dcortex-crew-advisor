from __future__ import annotations

import os
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pool: ConnectionPool | None = None


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy api/.env.example to api/.env.")
    return url


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=database_url(),
            min_size=1,
            max_size=10,
            kwargs={"prepare_threshold": None, "row_factory": dict_row},
            # Neon's pooled/pgbouncer endpoint already handles idle connections;
            open=True,
        )
    return _pool


@contextmanager
def get_cursor():
    """Acquires a connection from the pool (reused across calls, not
    reconnected every time) and yields a cursor. Commits on success."""
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
