"""Load the vendored dataset JSON files. Read-only -- never write under
crew-ops-advisor-dataset/, per docs/SETUP.md ("vendored, unmodified")."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from . import config


def _load(path) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"Expected vendored dataset file at {path}. Did the "
            f"crew-ops-advisor-dataset/ submodule/folder move?"
        )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@dataclass(frozen=True)
class Dataset:
    crew: list[dict]
    flights: list[dict]
    certifications: list[dict]
    duty_clocks: list[dict]
    reserve_pool: list[dict]
    rosters: dict
    rules: dict
    costs: dict
    risk_signals: list[dict]
    scenarios: list[dict]
    questions: list[dict]
    held_out_scenarios: list[dict]
    boarding_gates: list[dict]


def load_dataset() -> Dataset:
    d = config.DATA_DIR
    return Dataset(
        crew=_load(d / "crew.json"),
        flights=_load(d / "flights.json"),
        certifications=_load(d / "certifications.json"),
        duty_clocks=_load(d / "duty_clocks.json"),
        reserve_pool=_load(d / "reserve_pool.json"),
        rosters=_load(d / "rosters.json"),
        rules=_load(d / "rules.json"),
        costs=_load(d / "costs.json"),
        risk_signals=_load(d / "risk_signals.json"),
        scenarios=_load(d / "scenarios.json"),
        questions=_load(d / "questions.json"),
        held_out_scenarios=_load(config.INTERNAL_DIR / "held_out_scenarios.json"),
        # Fabricated, not vendored -- see mock_data/README.md.
        boarding_gates=_load(config.MOCK_DATA_DIR / "boarding_gate.json"),
    )
