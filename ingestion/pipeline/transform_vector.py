from __future__ import annotations

from typing import Any

from .loaders import Dataset


def _collect_reasoning(node: Any, out: list[str]) -> None:
    """Recursively collect every `reasoning` string under `node`. Deliberately
    does NOT collect `reason` (that's LEX's deterministic exclusion text --
    see module docstring)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "reasoning" and isinstance(v, str) and v:
                out.append(v)
            else:
                _collect_reasoning(v, out)
    elif isinstance(node, list):
        for item in node:
            _collect_reasoning(item, out)


def rule_records(ds: Dataset) -> list[dict]:
    records = []
    for r in ds.rules["rules"]:
        records.append(
            {
                "rule_id": r["rule_id"],
                "text": r["text"],
                "params": r.get("params", {}),
                "embed_text": r["text"],
            }
        )
    return records


def scenario_precedent_records(ds: Dataset) -> list[dict]:
    records = []
    for s in ds.scenarios:  # S1-S6 only -- held-out is never ingested, see docstring
        ak = s["answer_key"]
        parts: list[str] = []
        title = s.get("title")
        if title:
            parts.append(title)
        narrative = s.get("event", {}).get("narrative")
        if narrative:
            parts.append(narrative)
        _collect_reasoning(ak, parts)
        note = ak.get("note")
        if note:
            parts.append(note)
        records.append(
            {
                "scenario_id": s["scenario_id"],
                "difficulty": s.get("difficulty"),
                "event_type": s["event"]["type"],
                "answer_key": ak,
                "embed_text": "\n".join(parts),
            }
        )
    return records


def controller_note_records(ds: Dataset) -> list[dict]:
    records = []
    for e in ds.rosters["flagged_exceptions"]:
        records.append(
            {
                "crew_id": e["crew_id"],
                "date": e["date"],
                "rule": e["rule"],
                "note": e["note"],
            }
        )
    return records


def intent_example_records(ds: Dataset) -> list[dict]:
    records = []
    for q in ds.questions:
        parts = [q["prompt"]]
        explanation = q.get("explanation")
        if explanation:
            parts.append(explanation)
        ea = q.get("expected_answer")
        if isinstance(ea, dict) and ea.get("reasoning"):
            parts.append(ea["reasoning"])
        elif isinstance(ea, list):
            for item in ea:
                if isinstance(item, dict) and item.get("reasoning"):
                    parts.append(item["reasoning"])
        records.append(
            {
                "question_id": q["question_id"],
                "tier": q["tier"],
                "rules_ref": q.get("rules_ref", []),
                "prompt": q["prompt"],
                "embed_text": "\n".join(parts),
            }
        )
    return records
