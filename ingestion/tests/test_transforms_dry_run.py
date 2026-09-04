"""Dry-run tests: exercise every transform against the REAL vendored dataset,
with zero database dependency. This is what "the ingestion pipeline runs
without errors" actually means here, since no live Postgres is reachable in
this environment -- see ingestion/README.md for why, and how to run the real
thing once Postgres is available.

Run: cd ingestion && python -m pytest tests/ -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `pipeline` imports work when run from repo root too

from pipeline import config, transform_postgres as tp, transform_vector as tv, validate  # noqa: E402
from pipeline.loaders import load_dataset  # noqa: E402


@pytest.fixture(scope="module")
def ds():
    return load_dataset()


# ---------------------------------------------------------------- loaders

def test_dataset_loads_and_has_expected_top_level_shape(ds):
    assert len(ds.crew) == 150
    assert len(ds.flights) == 147
    assert len(ds.rosters["pairings"]) == 39
    assert len(ds.reserve_pool) == 16
    assert len(ds.rules["rules"]) == 7
    assert len(ds.scenarios) == 6
    assert len(ds.questions) == 38
    assert len(ds.held_out_scenarios) == 2


# ---------------------------------------------------------------- postgres transforms: run without error + row counts

@pytest.mark.parametrize(
    "transform_fn,expected_key",
    [
        (tp.crew_rows, "crew"),
        (tp.flight_rows, "flights"),
        (tp.certification_rows, "certifications"),
        (tp.duty_clock_rows, "duty_clocks"),
        (tp.duty_daily_history_rows, "duty_daily_history"),
        (tp.reserve_pool_rows, "reserve_pool"),
        (tp.pairing_rows, "pairings"),
        (tp.pairing_day_rows, "pairing_days"),
        (tp.pairing_day_flight_rows, "pairing_day_flights"),
        (tp.pairing_crew_rows, "pairing_crew"),
        (tp.roster_exception_rows, "roster_exceptions"),
        (tp.risk_signal_rows, "risk_signals"),
    ],
)
def test_postgres_transform_row_count_matches_expected(ds, transform_fn, expected_key):
    rows = transform_fn(ds)
    expected = validate.expected_counts(ds)[expected_key]
    assert len(rows) == expected, f"{expected_key}: got {len(rows)} rows, expected {expected}"


def test_costs_row_has_all_nine_fields(ds):
    row = tp.costs_row(ds)
    assert len(row) == 9
    assert row[0] == "INR"


def test_no_null_or_empty_primary_key_values(ds):
    for row in tp.crew_rows(ds):
        assert row[0], "crew_id must never be empty"
    for row in tp.flight_rows(ds):
        assert row[0], "flight_id must never be empty"
    for row in tp.pairing_rows(ds):
        assert row[0], "pairing_id must never be empty"


def test_pairing_day_flights_reference_only_real_flight_ids(ds):
    """FK integrity check before it ever hits Postgres: every flight_id
    referenced by a pairing day must exist in flights.json."""
    real_flight_ids = {f["flight_id"] for f in ds.flights}
    for pairing_id, date, flight_id, leg_order in tp.pairing_day_flight_rows(ds):
        assert flight_id in real_flight_ids, f"{flight_id} referenced by {pairing_id}/{date} not in flights.json"


def test_pairing_crew_reference_only_real_crew_ids(ds):
    real_crew_ids = {c["crew_id"] for c in ds.crew}
    for pairing_id, crew_id, role in tp.pairing_crew_rows(ds):
        assert crew_id in real_crew_ids, f"{crew_id} referenced by {pairing_id} not in crew.json"


def test_certifications_reference_only_real_crew_ids(ds):
    real_crew_ids = {c["crew_id"] for c in ds.crew}
    for crew_id, cert_type, valid_from, valid_to in tp.certification_rows(ds):
        assert crew_id in real_crew_ids


# ---------------------------------------------------------------- vector transforms: run without error + content checks

def test_rule_records_cover_all_seven_rules(ds):
    records = tv.rule_records(ds)
    assert {r["rule_id"] for r in records} == {
        "RULE-FDP-01", "RULE-DUTY-02", "RULE-FLT-03", "RULE-REST-04",
        "RULE-QUAL-05", "RULE-CERT-06", "RULE-BASE-07",
    }
    for r in records:
        assert r["embed_text"], f"{r['rule_id']} has empty embed_text"


def test_scenario_precedent_excludes_held_out(ds):
    records = tv.scenario_precedent_records(ds)
    ids = {r["scenario_id"] for r in records}
    assert ids == {"S1", "S2", "S3", "S4", "S5", "S6"}
    assert "H1" not in ids and "H2" not in ids, "held-out scenarios must never be ingested (DECISIONS.md #8)"


def test_scenario_precedent_s6_embed_text_contains_equal_cost_mirror_note(ds):
    """This is the concrete finding from docs/DATA_STORAGE_DESIGN.md §3b --
    make sure the transform actually captures it, not just that it exists in
    the raw JSON."""
    records = {r["scenario_id"]: r for r in tv.scenario_precedent_records(ds)}
    assert "equal-cost mirror" in records["S6"]["embed_text"].lower()


def test_scenario_precedent_embed_text_never_contains_deterministic_exclusion_reasons(ds):
    """Guards docs/DATA_STORAGE_DESIGN.md §3a: excluded_candidates[].reason
    text (LEX-computed) must never leak into the embedded narrative."""
    records = tv.scenario_precedent_records(ds)
    for r in records:
        # a real excluded_candidates reason string from S2, used as a canary
        assert "would exceed 60h/7d" not in r["embed_text"]


def test_controller_note_records_match_flagged_exceptions(ds):
    records = tv.controller_note_records(ds)
    assert len(records) == 1
    assert records[0]["crew_id"] == "C-5417"
    assert "recurrent_training" in records[0]["note"]


def test_intent_example_records_cover_all_38_questions_with_nonempty_text(ds):
    records = tv.intent_example_records(ds)
    assert len(records) == 38
    ids = {r["question_id"] for r in records}
    assert "Q02" in ids and "Q38" in ids
    for r in records:
        assert r["embed_text"].strip(), f"{r['question_id']} has empty embed_text"


def test_intent_example_q02_is_the_duty02_canary(ds):
    q02 = next(r for r in tv.intent_example_records(ds) if r["question_id"] == "Q02")
    assert q02["rules_ref"] == ["RULE-DUTY-02"]
    assert q02["tier"] == 1


# ---------------------------------------------------------------- SQL DDL: real Postgres grammar validation, no live server needed

def test_ddl_files_parse_as_valid_postgres_syntax():
    import pglast

    for filename in ("001_schema_postgres.sql", "002_schema_vector.sql"):
        sql = (config.SQL_DIR / filename).read_text(encoding="utf-8")
        stmts = pglast.parse_sql(sql)  # raises on syntax error
        assert len(stmts) > 0


# ---------------------------------------------------------------- embeddings: real model, real vectors, small sample only (keep test fast)

def test_local_embedder_produces_vectors_of_the_configured_dimension():
    from pipeline.embeddings import LocalEmbedder

    embedder = LocalEmbedder()
    vectors = embedder.embed(["Max flight duty period 13h.", "Min 12h rest between release and next report."])
    assert len(vectors) == 2
    assert all(len(v) == config.EMBEDDING_DIM for v in vectors)


def test_local_embedder_handles_empty_input():
    from pipeline.embeddings import LocalEmbedder

    embedder = LocalEmbedder()
    assert embedder.embed([]) == []
