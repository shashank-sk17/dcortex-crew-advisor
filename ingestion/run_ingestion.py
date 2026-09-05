#!/usr/bin/env python3
"""Ingestion CLI: vendored dataset JSON -> Postgres + pgvector.

Usage:
    python run_ingestion.py --all                 # schema + postgres + vector + validate
    python run_ingestion.py --schema               # apply DDL only
    python run_ingestion.py --postgres              # load structured tables only
    python run_ingestion.py --vector                 # embed + load vector tables only
    python run_ingestion.py --validate               # row-count check only
    python run_ingestion.py --all --reset-notes      # also truncate controller_note_vec first

Reads DATABASE_URL and EMBEDDING_PROVIDER from the environment (see .env.example).
Every Postgres/vector step is idempotent (ON CONFLICT DO UPDATE) except
controller_note_vec, which has no natural unique key -- use --reset-notes to
avoid duplicate rows across repeated runs.
"""
from __future__ import annotations

import argparse
import sys

from pipeline import config, db, load_postgres, load_vector, validate
from pipeline.embeddings import get_embedder
from pipeline.loaders import load_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--schema", action="store_true", help="apply DDL (both SQL files)")
    parser.add_argument("--postgres", action="store_true", help="load structured tables")
    parser.add_argument("--vector", action="store_true", help="embed + load vector tables")
    parser.add_argument("--validate", action="store_true", help="row-count check against source JSON")
    parser.add_argument("--all", action="store_true", help="schema + postgres + vector + validate")
    parser.add_argument(
        "--reset-notes",
        action="store_true",
        help="truncate controller_note_vec before loading (avoids duplicates on repeat runs)",
    )
    args = parser.parse_args()

    if args.all:
        args.schema = args.postgres = args.vector = args.validate = True

    if not any([args.schema, args.postgres, args.vector, args.validate]):
        parser.error("nothing to do -- pass --all or one of --schema/--postgres/--vector/--validate")

    settings = config.Settings.from_env()

    print(f"Loading vendored dataset from {config.DATA_DIR} ...")
    ds = load_dataset()
    print(
        f"  {len(ds.crew)} crew, {len(ds.flights)} flights, "
        f"{len(ds.rosters['pairings'])} pairings, {len(ds.scenarios)} scenarios, "
        f"{len(ds.questions)} questions"
    )

    try:
        conn = db.connect(settings)
    except Exception as exc:  # noqa: BLE001 -- top-level CLI: report and exit non-zero, don't traceback-spam
        print(f"ERROR: could not connect to {settings.database_url!r}: {exc}", file=sys.stderr)
        print("Is Postgres running? See ingestion/docker-compose.yml (`docker compose up -d`).", file=sys.stderr)
        return 1

    try:
        if args.schema:
            print(f"Applying schema ({', '.join(db.SCHEMA_FILES)}) ...")
            db.apply_schema(conn)
            print("  schema OK")

        if args.postgres:
            print("Loading structured tables into Postgres ...")
            counts = load_postgres.load_all(conn, ds)
            for table, n in counts.items():
                print(f"  {table:<24} {n:>5} rows")

        if args.vector:
            print(f"Loading vector collections (embedding provider: {settings.embedding_provider}) ...")
            embedder = get_embedder(settings)
            counts = load_vector.load_all(conn, ds, embedder, reset_notes=args.reset_notes)
            for table, n in counts.items():
                print(f"  {table:<24} {n:>5} rows")

        if args.validate:
            print("Validating row counts against source JSON ...")
            results = validate.validate(conn, ds)
            all_ok = True
            for r in results:
                status = "OK" if r.ok else "MISMATCH"
                if not r.ok:
                    all_ok = False
                print(f"  {r.table:<24} expected={r.expected:<5} actual={r.actual:<5} {status}")
            if not all_ok:
                print("VALIDATION FAILED", file=sys.stderr)
                return 1
            print("All row counts match.")

    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"ERROR during ingestion: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
