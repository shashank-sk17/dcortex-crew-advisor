"""Read-only Postgres tool port.

Satisfies `agent.tools.ToolPort` against the Neon database, so the agent can be
exercised on real data before `core/` exists.

**Every connection is opened read-only** (`SET default_transaction_read_only`),
so nothing here can write, and a bug that tries to will raise rather than
mutate. The database is a teammate's work; this only reads it.

Scope is deliberate. `lookup`, `duty_clock` and `explain_rule` are pure
queries, so they are implemented. The legality tools — `check_legality`,
`find_options`, `ripple`, `simulate`, `joint_plan` — need the rules engine,
which is Kashifa's `core/` (issues #3-#12). They raise `ToolError` rather than
returning a plausible verdict, for the same reason `PlaceholderToolPort` does:
a stub that lies is worse than one that refuses.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from agent.tools import ToolError

try:
    import psycopg
except ImportError:  # keeps the package importable without the driver
    psycopg = None  # type: ignore[assignment]

REPO_ROOT = Path(__file__).resolve().parent.parent

# entity name -> (table, default order column)
TABLES: dict[str, tuple[str, str]] = {
    "crew": ("crew", "crew_id"),
    "flights": ("flights", "flight_id"),
    "pairings": ("pairings", "pairing_id"),
    "reserves": ("reserve_pool", "crew_id"),
    "certifications": ("certifications", "crew_id"),
    "risk_signals": ("risk_signals", "crew_id"),
    "costs": ("costs", "id"),
    "duty_clocks": ("duty_clocks", "crew_id"),
    "pairing_days": ("pairing_days", "pairing_id"),
    "pairing_crew": ("pairing_crew", "pairing_id"),
    "rules": ("rules_vec", "rule_id"),
}

MAX_ROWS = 500


def load_database_url() -> str | None:
    """`DATABASE_URL` from the environment, else from a local .env."""
    if url := os.environ.get("DATABASE_URL"):
        return url
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return None


class PostgresToolPort:
    """Read-only adapter over the operational schema."""

    def __init__(self, url: str | None = None) -> None:
        if psycopg is None:
            raise ToolError("INTERNAL", "psycopg not installed: pip install 'psycopg[binary]'")
        resolved = url or load_database_url()
        if not resolved:
            raise ToolError("INTERNAL", "no DATABASE_URL in the environment or .env")
        self.url = resolved

    # -- plumbing ---------------------------------------------------------

    def _connect(self) -> Any:
        conn = psycopg.connect(self.url, connect_timeout=20)
        conn.read_only = True  # refuses writes at the server, not by convention
        return conn

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    return []
                cols = [c.name for c in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError("INTERNAL", f"query failed: {type(exc).__name__}: {exc}") from exc

    @lru_cache(maxsize=32)
    def _columns(self, table: str) -> frozenset[str]:
        """Real column names, so filter keys can be whitelisted rather than
        interpolated. Nothing from the model ever reaches SQL as an identifier."""
        rows = self._query(
            "select column_name from information_schema.columns "
            "where table_schema='public' and table_name=%s",
            (table,),
        )
        return frozenset(r["column_name"] for r in rows)

    # -- ToolPort ---------------------------------------------------------

    def lookup(self, entity: str, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if entity not in TABLES:
            raise ToolError(
                "UNRESOLVED_ENTITY",
                f"unknown entity {entity!r}; known: {', '.join(sorted(TABLES))}",
            )
        table, order = TABLES[entity]
        known = self._columns(table)

        where, params = [], []
        for key, value in (filters or {}).items():
            if key not in known:
                raise ToolError(
                    "UNRESOLVED_ENTITY",
                    f"{table} has no column {key!r}; known: {', '.join(sorted(known))}",
                )
            if isinstance(value, (list, tuple)):
                where.append(f'"{key}" = any(%s)')
                params.append(list(value))
            else:
                where.append(f'"{key}" = %s')
                params.append(value)

        clause = (" where " + " and ".join(where)) if where else ""
        cols = ", ".join(f'"{c}"' for c in sorted(known) if c not in {"embedding", "search_tsv"})
        return self._query(
            f'select {cols} from "{table}"{clause} order by "{order}" limit {MAX_ROWS}',
            tuple(params),
        )

    def duty_clock(self, crew_id: str, date_: str | None = None, **kw: Any) -> dict[str, Any]:
        """Accrued hours and headroom on a calendar-day window.

        Windows are calendar days inclusive of the duty date, per rules.json —
        not rolling 168/672-hour windows. See docs/RULES.md, trap 1.
        """
        date_ = date_ or kw.get("date")
        rows = self._query(
            "select crew_id, as_of_utc, duty_hours_7d, flight_hours_28d, last_rest_ended "
            "from duty_clocks where crew_id = %s",
            (crew_id,),
        )
        if not rows:
            raise ToolError("UNRESOLVED_ENTITY", f"no duty clock for {crew_id!r}")
        clock = rows[0]

        end = date.fromisoformat(date_) if date_ else clock["as_of_utc"].date()
        window = self._query(
            "select coalesce(sum(duty_hours), 0) as duty, coalesce(sum(flight_hours), 0) as flight "
            "from duty_daily_history where crew_id = %s and date between %s and %s",
            (crew_id, end - timedelta(days=6), end),
        )[0]
        flight28 = self._query(
            "select coalesce(sum(flight_hours), 0) as flight "
            "from duty_daily_history where crew_id = %s and date between %s and %s",
            (crew_id, end - timedelta(days=27), end),
        )[0]

        duty7 = float(window["duty"])
        blk28 = float(flight28["flight"])
        return {
            "crew_id": crew_id,
            "window_end": end.isoformat(),
            "duty_hours_7d": round(duty7, 2),
            "headroom_hours": round(60.0 - duty7, 2),
            "flight_hours_28d": round(blk28, 2),
            "flight_headroom_hours": round(100.0 - blk28, 2),
            "last_rest_ended": clock["last_rest_ended"],
            "rules_ref": ["RULE-DUTY-02", "RULE-FLT-03"],
        }

    def explain_rule(self, rule_id: str) -> dict[str, Any]:
        rows = self._query(
            "select rule_id, text, params from rules_vec where rule_id = %s", (rule_id,)
        )
        if not rows:
            raise ToolError("UNRESOLVED_ENTITY", f"no rule {rule_id!r}")
        return rows[0]

    def search_rules(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        """Lexical search over the rulebook.

        Uses the existing `search_tsv` column rather than embeddings: nothing
        records which model produced the stored 384-dim vectors, so a query
        embedded with a different model would degrade silently.

        Terms are OR-ed, not AND-ed. `plainto_tsquery` requires every term, and
        against seven short rules with a narrow vocabulary that returns nothing
        for most real questions — "rest between duties" demands a 'duti' token
        RULE-REST-04 does not contain. OR plus `ts_rank` keeps precision in the
        ordering while still returning the obvious match.
        """
        return self._query(
            "with q as (select string_to_array(lower(regexp_replace(%s, '[^a-zA-Z0-9 ]', ' ', 'g')), ' ') terms) "
            "select rule_id, text, "
            "       ts_rank(search_tsv, to_tsquery('english', qq)) as rank "
            "from rules_vec, "
            "     (select nullif(array_to_string(array(select t from unnest((select terms from q)) t "
            "        where length(t) > 2), ' | '), '') qq) s "
            "where qq is not null and search_tsv @@ to_tsquery('english', qq) "
            "order by rank desc limit %s",
            (query, limit),
        )

    # -- deferred to core/ -------------------------------------------------

    _NOT_YET = "needs the rules engine in core/ — see issues #3-#12"

    def check_legality(self, crew_id: str, pairing_id: str, delay_h: float = 0.0) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"check_legality: {self._NOT_YET}")

    def find_options(self, pairing_id: str, role: str, callout_utc: str | None = None) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"find_options: {self._NOT_YET}")

    def ripple(self, event: dict[str, Any]) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"ripple: {self._NOT_YET}")

    def simulate(self, event: dict[str, Any]) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"simulate: {self._NOT_YET}")

    def joint_plan(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        raise ToolError("INTERNAL", f"joint_plan: {self._NOT_YET}")
