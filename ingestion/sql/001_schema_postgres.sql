-- 001_schema_postgres.sql
-- Structured operational data. See docs/DATA_STORAGE_DESIGN.md §2.
--
-- Normalization notes:
--   - crew.ratings and risk_signals.drivers are kept as native arrays, not join
--     tables. Nothing in the dataset filters on individual rating/driver values
--     independently of their owning row, so a join table would add write/read
--     overhead for zero query benefit at this scale.
--   - duty_clocks.daily_history IS split into its own table (duty_daily_history),
--     because RULE-DUTY-02 / RULE-FLT-03 sum it over arbitrary calendar-day
--     windows -- that needs row-per-day so a plain SQL date-range SUM works.
--   - rosters.json is split into pairings / pairing_days / pairing_day_flights /
--     pairing_crew because each level is independently queried (e.g. "who is on
--     P-2291" vs "what flights does day 1 cover").
--
-- Run order: this file, then 002_schema_vector.sql.

BEGIN;

-- ---------------------------------------------------------------- crew
CREATE TABLE IF NOT EXISTS crew (
    crew_id             TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    rank                TEXT NOT NULL CHECK (rank IN ('Captain', 'First Officer', 'Senior Cabin Crew', 'Cabin Crew')),
    base                TEXT NOT NULL,
    ratings             TEXT[] NOT NULL DEFAULT '{}',
    seniority           INTEGER NOT NULL,
    reachability_minutes INTEGER NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('active', 'leave', 'training'))
);
CREATE INDEX IF NOT EXISTS idx_crew_rank_base_status ON crew (rank, base, status);
CREATE INDEX IF NOT EXISTS idx_crew_ratings_gin ON crew USING GIN (ratings);

-- ---------------------------------------------------------------- flights
CREATE TABLE IF NOT EXISTS flights (
    flight_id       TEXT PRIMARY KEY,
    flight_no       TEXT NOT NULL,
    date            DATE NOT NULL,
    dep_station     TEXT NOT NULL,
    arr_station     TEXT NOT NULL,
    dep_utc         TIMESTAMPTZ NOT NULL,
    arr_utc         TIMESTAMPTZ NOT NULL,
    block_hours     NUMERIC(5,2) NOT NULL,
    aircraft        TEXT NOT NULL,
    aircraft_type   TEXT NOT NULL,
    seats           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_flights_dep_station_date ON flights (dep_station, date);
CREATE INDEX IF NOT EXISTS idx_flights_arr_station_date ON flights (arr_station, date);
CREATE INDEX IF NOT EXISTS idx_flights_aircraft ON flights (aircraft);
CREATE INDEX IF NOT EXISTS idx_flights_flight_no_date ON flights (flight_no, date);

-- ---------------------------------------------------------------- certifications
CREATE TABLE IF NOT EXISTS certifications (
    crew_id     TEXT NOT NULL REFERENCES crew (crew_id),
    cert_type   TEXT NOT NULL,
    valid_from  DATE NOT NULL,
    valid_to    DATE NOT NULL,
    PRIMARY KEY (crew_id, cert_type)
);
CREATE INDEX IF NOT EXISTS idx_certifications_valid_to ON certifications (valid_to);

-- ---------------------------------------------------------------- duty clocks
CREATE TABLE IF NOT EXISTS duty_clocks (
    crew_id             TEXT PRIMARY KEY REFERENCES crew (crew_id),
    as_of_utc           TIMESTAMPTZ NOT NULL,
    duty_hours_7d       NUMERIC(6,2) NOT NULL,
    flight_hours_28d    NUMERIC(6,2) NOT NULL,
    last_rest_ended     TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS duty_daily_history (
    crew_id     TEXT NOT NULL REFERENCES crew (crew_id),
    date        DATE NOT NULL,
    duty_hours  NUMERIC(5,2) NOT NULL,
    flight_hours NUMERIC(5,2) NOT NULL,
    PRIMARY KEY (crew_id, date)
);
CREATE INDEX IF NOT EXISTS idx_duty_daily_history_date ON duty_daily_history (date);

-- ---------------------------------------------------------------- reserve pool
CREATE TABLE IF NOT EXISTS reserve_pool (
    crew_id             TEXT PRIMARY KEY REFERENCES crew (crew_id),
    base                TEXT NOT NULL,
    dates               DATE[] NOT NULL DEFAULT '{}',
    oncall_start_utc    TIME NOT NULL,
    oncall_end_utc      TIME NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reserve_pool_base ON reserve_pool (base);

-- ---------------------------------------------------------------- pairings / rosters
CREATE TABLE IF NOT EXISTS pairings (
    pairing_id  TEXT PRIMARY KEY,
    aircraft    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pairing_days (
    pairing_id      TEXT NOT NULL REFERENCES pairings (pairing_id),
    date            DATE NOT NULL,
    report_utc      TIMESTAMPTZ NOT NULL,
    release_utc     TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (pairing_id, date)
);

CREATE TABLE IF NOT EXISTS pairing_day_flights (
    pairing_id  TEXT NOT NULL,
    date        DATE NOT NULL,
    flight_id   TEXT NOT NULL REFERENCES flights (flight_id),
    leg_order   INTEGER NOT NULL,
    PRIMARY KEY (pairing_id, date, flight_id),
    FOREIGN KEY (pairing_id, date) REFERENCES pairing_days (pairing_id, date)
);
CREATE INDEX IF NOT EXISTS idx_pairing_day_flights_flight ON pairing_day_flights (flight_id);

CREATE TABLE IF NOT EXISTS pairing_crew (
    pairing_id  TEXT NOT NULL REFERENCES pairings (pairing_id),
    crew_id     TEXT NOT NULL REFERENCES crew (crew_id),
    role        TEXT NOT NULL,
    PRIMARY KEY (pairing_id, crew_id)
);
CREATE INDEX IF NOT EXISTS idx_pairing_crew_crew ON pairing_crew (crew_id);

CREATE TABLE IF NOT EXISTS roster_exceptions (
    crew_id     TEXT NOT NULL REFERENCES crew (crew_id),
    date        DATE NOT NULL,
    rule        TEXT NOT NULL,
    note        TEXT NOT NULL,
    PRIMARY KEY (crew_id, date, rule)
);

-- ---------------------------------------------------------------- costs (single-row reference table)
CREATE TABLE IF NOT EXISTS costs (
    id                          BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),  -- enforces exactly one row
    currency                    TEXT NOT NULL,
    reserve_callout_pilot       INTEGER NOT NULL,
    reserve_callout_cabin       INTEGER NOT NULL,
    dayoff_callout_pilot        INTEGER NOT NULL,
    dayoff_callout_cabin        INTEGER NOT NULL,
    deadhead_positioning        INTEGER NOT NULL,
    delay_cost_per_duty_hour    INTEGER NOT NULL,
    cancellation_per_flight     INTEGER NOT NULL,
    hotel_overnight             INTEGER NOT NULL
);

-- ---------------------------------------------------------------- risk signals
-- Whole rows, exact-queried, reformatted for display. No embedding -- see
-- docs/DATA_STORAGE_DESIGN.md §1/§3 for why this stays out of the vector DB.
CREATE TABLE IF NOT EXISTS risk_signals (
    crew_id                 TEXT PRIMARY KEY REFERENCES crew (crew_id),
    as_of_utc               TIMESTAMPTZ NOT NULL,
    disruption_risk_score   NUMERIC(4,3) NOT NULL,
    drivers                 TEXT[] NOT NULL DEFAULT '{}'
);

COMMIT;
