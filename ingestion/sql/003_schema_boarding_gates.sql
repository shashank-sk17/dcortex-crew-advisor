-- 003_schema_boarding_gates.sql
-- Boarding-gate assignments. Fabricated, not vendored -- see mock_data/README.md.
-- One row per real flight leg; only boarding_gate_number is invented, the
-- rest (window, aircraft_type) is derived from the real flight schedule.
--
-- No embedding / vector table: this is exact-lookup data (a claim checked
-- against a fact), same reasoning as risk_signals in 001_schema_postgres.sql.
--
-- Run order: after 001_schema_postgres.sql (flights must already exist).

BEGIN;

CREATE TABLE IF NOT EXISTS boarding_gates (
    flight_id               TEXT PRIMARY KEY REFERENCES flights (flight_id),
    boarding_gate_number    TEXT NOT NULL,
    pairing_id              TEXT,
    date                    DATE NOT NULL,
    boarding_start_time     TIMESTAMPTZ NOT NULL,
    boarding_end_time       TIMESTAMPTZ NOT NULL,
    aircraft_type           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_boarding_gates_gate_window
    ON boarding_gates (boarding_gate_number, boarding_start_time);

COMMIT;
