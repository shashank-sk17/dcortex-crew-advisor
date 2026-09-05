"""Generate frontend fixtures from dCortex's own answer keys.

    python -m evals.make_fixtures

Per DECISIONS.md #3, fixtures are lifted from the answer keys rather than
invented — so what Kiran builds against IS the correct answer, and the swap to
the real engine is a no-op rather than a rewrite.

Everything here is a reshape of `scenarios.json` into the response bodies in
`docs/API_CONTRACT.md`. No number is computed; the funnel counts are lengths of
the key's own lists, and `equal_cost_alternatives` counts options already
sharing a cost.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from agent import config

OUT = Path(__file__).resolve().parent / "fixtures"

RULE_RE = re.compile(r"RULE-[A-Z]{3,4}-\d{2}")

# How an exclusion reason maps onto a funnel stage, most specific first.
STAGES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("qualified", "no rating for the aircraft type", re.compile(r"RULE-QUAL-05")),
    ("certified", "certification invalid on the duty date", re.compile(r"RULE-CERT-06")),
    ("in position", "no same-day positioning from base", re.compile(r"RULE-BASE-07")),
    ("on call", "reserve window does not cover report time", re.compile(r"on-call window")),
    ("available", "already rostered / double-booked", re.compile(r"double-booked|overlaps")),
    ("rested", "insufficient rest", re.compile(r"RULE-REST-04")),
    ("within limits", "duty or block-hour limit exceeded",
     re.compile(r"RULE-DUTY-02|RULE-FLT-03|RULE-FDP-01")),
)


def stage_for(reason: str) -> tuple[str, str]:
    for stage, label, pattern in STAGES:
        if pattern.search(reason):
            return stage, label
    return "other", "excluded"


def build_funnel(options: list[dict], excluded: list[dict]) -> list[dict[str, Any]]:
    """Narrowing steps, with the reason for every drop.

    Counts are lengths of the answer key's own lists — nothing is derived by
    arithmetic the tools did not produce.
    """
    grouped = Counter(stage_for(e.get("reason", ""))[0] for e in excluded)
    labels = {stage: label for stage, label, _ in STAGES}
    labels["other"] = "excluded"

    remaining = len(options) + len(excluded)
    funnel = [{"stage": "considered", "count": remaining, "dropped": 0, "reason": ""}]

    for stage, _, _ in STAGES:
        dropped = grouped.get(stage, 0)
        if not dropped:
            continue
        remaining -= dropped
        funnel.append({"stage": stage, "count": remaining,
                       "dropped": dropped, "reason": labels[stage]})

    if other := grouped.get("other", 0):
        remaining -= other
        funnel.append({"stage": "other", "count": remaining,
                       "dropped": other, "reason": "excluded"})

    funnel.append({"stage": "legal", "count": len(options), "dropped": 0, "reason": ""})
    return funnel


def reshape_excluded(excluded: list[dict]) -> list[dict[str, Any]]:
    """Answer-key exclusions carry prose; the UI wants rule ids alongside."""
    out = []
    for row in excluded:
        reason = row.get("reason", "")
        out.append({
            "crew_id": row.get("crew_id"),
            "reason": reason,
            "rules": sorted(set(RULE_RE.findall(reason))),
            "verdicts": [
                {"rule_id": rid, "status": "FAIL", "detail": reason}
                for rid in sorted(set(RULE_RE.findall(reason)))
            ],
        })
    return out


def equal_cost_alternatives(plan: dict, options: list[dict], n_events: int = 2) -> int:
    """How many distinct assignments hit the same optimal total.

    S6 comes to 20: one ₹18,500 reserve and ten ₹24,000 day-off captains gives
    10 pairs, doubled because the two pairings are interchangeable — dCortex's
    own note calls those mirrors "equally correct".

    The mirror factor is the easy thing to drop, and dropping it understates
    the count by half. The UI must never present one plan as uniquely right
    (DECISIONS.md #12).
    """
    costs = Counter(o["cost_inr"] for o in options if o.get("legal"))
    if not costs:
        return 1
    cheapest = min(costs)
    second = min((c for c in costs if c > cheapest), default=cheapest)
    pairs = costs[cheapest] * costs.get(second, 0)
    # Which disruption gets the cheap option is a free choice.
    mirrors = n_events if n_events > 1 else 1
    return (pairs * mirrors) or 1


def replacement_body(ak: dict) -> dict[str, Any]:
    options = ak.get("options", [])
    excluded = ak.get("excluded_candidates", [])
    return {
        "kind": "replacement",
        "uncovered_flights": ak.get("uncovered_flights")
                             or ak.get("uncovered_flights_day1", []),
        "at_risk_flights": ak.get("uncovered_flights_day2", []),
        "passengers_affected": ak.get("passengers_at_risk_day1", 0),
        "funnel": build_funnel(options, excluded),
        "options": options,
        "near_misses": [o for o in options if not o.get("legal")],
        "excluded": reshape_excluded(excluded),
    }


def consequence_body(scenario: dict) -> dict[str, Any]:
    ak = scenario["answer_key"]
    body: dict[str, Any] = {"kind": "consequence", "options": ak.get("options", [])}

    if plan := ak.get("optimal_joint_plan"):
        n_events = len(scenario["event"].get("events", [])) or 2
        body["joint_plan"] = {
            **plan,
            "equal_cost_alternatives": equal_cost_alternatives(
                plan, ak.get("options_dxa", []), n_events),
            "note": ak.get("note", ""),
        }
        body["options"] = ak.get("options_dxa", [])
        body["funnel"] = build_funnel(ak.get("options_dxa", []),
                                      ak.get("excluded_dxa", []))
        body["excluded"] = reshape_excluded(ak.get("excluded_dxa", []))

    if affected := ak.get("affected_flights"):
        body["blast_radius"] = {
            "nodes": len(affected),
            "flights": len(affected),
            "aircraft": len({a.get("pairing_id") for a in ak.get("per_flight_assessment", [])}),
            "passengers": 0,
            "edges": [{"from": scenario["event"]["type"], "to": f, "kind": "direct"}
                      for f in affected],
        }
        body["world_diff"] = {"changed": ak.get("per_flight_assessment", [])}

    if ak.get("breach"):
        body["world_diff"] = {"changed": [{
            "rule_id": "RULE-FDP-01",
            "fdp_after_delay": ak["fdp_after_delay"],
            "fdp_limit": ak["fdp_limit"],
            "detail": ak.get("breach_detail", ""),
        }]}

    return body


def main() -> int:
    scenarios = json.loads((config.DATA_DIR / "scenarios.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)

    index = []
    for s in scenarios:
        sid = s["scenario_id"]
        ak = s["answer_key"]
        is_consequence = bool(
            ak.get("optimal_joint_plan") or ak.get("affected_flights") or ak.get("breach")
        )
        body = consequence_body(s) if is_consequence else replacement_body(ak)

        payload = {
            "scenario_id": sid,
            "title": s["title"],
            "difficulty": s["difficulty"],
            "event": s["event"],
            "tier": 3 if is_consequence else 2,
            "answer": body,
            "expected_choice": ak.get("expected_choice"),
        }
        (OUT / f"{sid}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")

        n_opts = len(body.get("options", []))
        n_funnel = len(body.get("funnel", []))
        index.append({"scenario_id": sid, "title": s["title"],
                      "difficulty": s["difficulty"], "tier": payload["tier"],
                      "event_type": s["event"]["type"]})
        print(f"  {sid}  tier {payload['tier']}  {n_opts:>2} options  "
              f"{n_funnel} funnel stages  {s['title']}")

    (OUT / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"\n  wrote {len(scenarios) + 1} files to {OUT.relative_to(config.REPO_ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
