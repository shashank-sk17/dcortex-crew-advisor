"""
Reference mock server for the reconciled API contract.

    python -m api.mock            # serves on http://localhost:5000

It is the FROZEN reference emitter (replaces the starter's contract/mock_backend.py).
Kiran builds the console against this; the mock -> real swap is one env var
(`environment.useMock = false`) once `api/app.py` (the real Flask app over `core/`)
satisfies `evals/contract_test.py`.

What is real here:
  - /health, /rules, /scenarios      read straight from the vendored dataset
  - /rank                            real deterministic weighted re-rank (no LLM)
What is scripted:
  - /ask                             keyword-routed to a fixture in evals/fixtures/ask/
                                     lifted from the dataset answer keys, then streamed
                                     as the reconciled SSE event sequence.

See docs/CONTRACT_RECONCILIATION.md for the event shapes.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request
from flask_cors import CORS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "crew-ops-advisor-dataset" / "data"
FIX = ROOT / "evals" / "fixtures"

app = Flask(__name__)
CORS(app)


# --------------------------------------------------------------------------- data
def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CREW = _load(DATA / "crew.json")
FLIGHTS = _load(DATA / "flights.json")
RULES = _load(DATA / "rules.json")
RESERVES = _load(DATA / "reserve_pool.json")
SCENARIOS = _load(FIX / "scenarios.json")

ASK_FIXTURES = []
for f in sorted((FIX / "ask").glob("*.json")):
    fx = _load(f)
    fx["_name"] = f.stem
    ASK_FIXTURES.append(fx)


# ---------------------------------------------------------------------- routing
def route_query(query: str) -> dict:
    """Keyword-match a query to a fixture. Falls back to abstain."""
    q = (query or "").lower()
    best = None
    for fx in ASK_FIXTURES:
        needles = fx.get("match", {}).get("any", [])
        hits = sum(1 for n in needles if n in q)
        if hits and (best is None or hits > best[0]):
            best = (hits, fx)
    if best:
        return best[1]
    return next(fx for fx in ASK_FIXTURES if fx["_name"] == "abstain")


def scenario_fixture(scenario_id: str) -> dict:
    mapping = {
        "S1": "s2_replacement",
        "S2": "s2_consequence",
        "S3": "s2_consequence",
        "S4": "s2_consequence",
        "S5": "s2_consequence",
        "S6": "s2_consequence",
    }
    name = mapping.get(scenario_id.upper(), "s2_consequence")
    return next(fx for fx in ASK_FIXTURES if fx["_name"] == name)


# ------------------------------------------------------------------- SSE stream
def sse(event: str, data: dict) -> str:
    payload = {"type": event, **data}
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_fixture(fx: dict):
    """Emit the reconciled event sequence for a fixture, with human-paced gaps."""
    t0 = time.time()

    if fx.get("status"):
        yield sse("status", {"text": fx["status"]})
        time.sleep(0.15)

    for step in fx.get("trace", []):
        yield sse("tool_call", {"id": step.get("tool", "t") + "-c",
                                "tool": step["tool"], "args": step.get("args", {})})
        time.sleep(0.35)
        yield sse("tool_result", {"id": step.get("tool", "t") + "-c", "tool": step["tool"],
                                  "summary": step.get("summary", ""),
                                  "data": step.get("data", {}), "ms": step.get("ms", 10)})
        time.sleep(0.2)

    for rc in fx.get("rule_checks", []):
        yield sse("rule_check", rc)
        time.sleep(0.18)

    if fx.get("abstain"):
        yield sse("abstain", fx["abstain"])
        yield sse("done", {"elapsed_ms": int((time.time() - t0) * 1000),
                           "grounded": fx.get("grounded", True)})
        return

    for word in (fx.get("narration", "") or "").split(" "):
        if word:
            yield sse("token", {"text": word + " "})
            time.sleep(0.03)

    ans = fx["answer"]
    yield sse("answer", {
        "tier": ans["tier"], "intent": ans.get("intent", ""),
        "entities": ans.get("entities", {}), "answer": ans["answer"],
        "narrative": ans.get("narrative", ""), "citations": ans.get("citations", []),
        "confidence": ans.get("confidence", "medium"), "unknowns": ans.get("unknowns", []),
    })
    yield sse("done", {"elapsed_ms": int((time.time() - t0) * 1000),
                       "grounded": fx.get("grounded", True)})


def non_stream_body(fx: dict) -> dict:
    if fx.get("abstain"):
        return {"error": {"code": "OUT_OF_SCOPE", "message": fx["abstain"]["reason"],
                          "needed": fx["abstain"]["needed"]},
                "trace": fx.get("trace", [])}
    ans = fx["answer"]
    return {**ans, "trace": [{"tool": s["tool"], "args": s.get("args", {}), "ms": s.get("ms", 10)}
                             for s in fx.get("trace", [])]}


# --------------------------------------------------------------------- endpoints
@app.get("/api/v1/health")
def health():
    return jsonify({"world_loaded": True, "crew": len(CREW), "flights": len(FLIGHTS),
                    "mode": "mock", "fixtures": [fx["_name"] for fx in ASK_FIXTURES]})


@app.get("/api/v1/rules")
def rules():
    return jsonify(RULES)


@app.get("/api/v1/scenarios")
def scenarios():
    return jsonify(SCENARIOS)


@app.post("/api/v1/ask")
def ask():
    body = request.get_json(silent=True) or {}
    query = body.get("query", "")
    fx = route_query(query)
    if body.get("stream"):
        return Response(stream_fixture(fx), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return jsonify(non_stream_body(fx))


@app.post("/api/v1/scenarios/<scenario_id>/run")
def run_scenario(scenario_id: str):
    body = request.get_json(silent=True) or {}
    fx = scenario_fixture(scenario_id)
    if body.get("stream"):
        return Response(stream_fixture(fx), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    return jsonify(non_stream_body(fx))


@app.post("/api/v1/rank")
def rank():
    """Deterministic weighted re-rank — the policy-slider path. No LLM."""
    body = request.get_json(silent=True) or {}
    options = body.get("options", [])
    w = {"cost": 1.0, "delay": 1.0, "pool": 0.5, "pairing": 0.8, "fairness": 0.3, **body.get("weights", {})}

    def score(o: dict) -> float:
        cost = o.get("cost_inr", 0) / 1000.0
        delay = o.get("delay_hours", 0.0)
        pool_hit = 1.0 if "reserve callout" in o.get("action", "").lower() else 0.0
        blast = o.get("blast_radius", 0) or 0
        return (w["cost"] * cost) + (w["delay"] * delay * 5.4) + (w["pool"] * pool_hit * 3.0) + (w["pairing"] * blast * 2.0)

    legal = [o for o in options if o.get("legal")]
    illegal = [o for o in options if not o.get("legal")]
    legal.sort(key=score)
    ranked = []
    for i, o in enumerate(legal + illegal, start=1):
        ranked.append({**o, "rank": i, "_score": round(score(o), 2)})
    return jsonify({"options": ranked, "weights": w})


if __name__ == "__main__":
    print("Crew Ops Advisor MOCK  →  http://localhost:5000/api/v1/health")
    print("  POST /api/v1/ask            {\"query\": \"...\", \"stream\": true}")
    print("  POST /api/v1/scenarios/S2/run  {\"stream\": true}")
    app.run(port=5000, debug=True, threaded=True)
