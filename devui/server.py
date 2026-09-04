"""Dev console for exercising the agent. Standard library only.

    python -m devui.server          # http://localhost:8420

Deliberately NOT the production console — that is Kiran's Angular workspace in
`frontend/` (issues #31-#39). This is a disposable debugging instrument that
runs the agent in-process and shows every pipeline stage, so nothing here
should be imported by anything else.

Stdlib `http.server` rather than Flask: it keeps `requirements.txt` honest
while `api/` is unstarted, and this needs no framework.
"""

from __future__ import annotations

import errno
import json
import os
import sys
import traceback
from functools import lru_cache
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import parse_qs, urlparse

from agent import config
from agent.advisor import Advisor, seed_calls, tools_for
from agent.entities import extract, mask
from agent.exemplars import load_exemplars
from agent.llm import PlaceholderLLM
from agent.router import route
from agent.schemas import Intent
from agent.tools import TOOL_NAMES, TOOL_SCHEMAS, PlaceholderToolPort
from agent.verifier import build_evidence, verify

STATIC = Path(__file__).resolve().parent / "static"
PORT = 8420

# Backends, chosen by env var so the same console drives every combination:
#   AGENT_LLM   placeholder (default) | ollama
#   AGENT_DATA  json (default)        | postgres
LLM_KIND = os.environ.get("AGENT_LLM", "placeholder").lower()
DATA_KIND = os.environ.get("AGENT_DATA", "json").lower()
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")


def make_llm() -> tuple[Any, str]:
    """Return the configured client and a label for the status bar."""
    if LLM_KIND == "ollama":
        from agent.llm_ollama import OllamaLLM

        client = OllamaLLM(OLLAMA_MODEL)
        if not client.available():
            return PlaceholderLLM(), f"ollama unreachable — using placeholder"
        return client, f"ollama {OLLAMA_MODEL}"
    return PlaceholderLLM(), "placeholder"


def make_port() -> tuple[Any, str]:
    if DATA_KIND == "fixtures":
        from agent.tools_fixtures import FixtureToolPort

        return FixtureToolPort(), "answer-key fixtures"
    if DATA_KIND == "postgres":
        from agent.tools_postgres import PostgresToolPort

        try:
            return PostgresToolPort(), "postgres (read-only)"
        except Exception as exc:
            return PlaceholderToolPort(), f"postgres failed ({exc}) — using json"
    return PlaceholderToolPort(), "vendored json"


@lru_cache(maxsize=1)
def backends() -> tuple[Any, str, Any, str]:
    llm, llm_label = make_llm()
    port, port_label = make_port()
    return llm, llm_label, port, port_label


# --------------------------------------------------------------------------
# Pipeline introspection
# --------------------------------------------------------------------------


def _stage_status(ran: bool, degraded: bool = False) -> str:
    if not ran:
        return "skipped"
    return "degraded" if degraded else "ok"


def run_pipeline(query: str) -> dict[str, Any]:  # noqa: C901
    """Run the agent and report what every stage did.

    The stages are re-derived rather than instrumented inside `agent/` — the
    advisor's own contract stays clean and this file stays disposable.
    """
    import time
    started = time.perf_counter()
    llm, _, port, _ = backends()
    entities = extract(query)
    decision = route(query)
    planned = seed_calls(decision)

    advisor = Advisor(port=port, llm=llm)
    response = advisor.ask(query)

    verification = verify(response.narrative, response.trace)
    evidence = build_evidence(response.trace)

    errored = [e for e in response.trace if e.error]

    return {
        "query": query,
        "stages": [
            {
                "key": "router",
                "name": "Router",
                "status": _stage_status(True, decision.confidence.value == "low"),
                "summary": f"tier {int(decision.tier)} · {decision.intent}",
                "detail": {
                    "intent": str(decision.intent),
                    "tier": int(decision.tier),
                    "matched_rule": decision.matched_rule,
                    "used_llm": decision.used_llm,
                    "confidence": str(decision.confidence),
                    "notes": decision.notes,
                    "masked": mask(query),
                },
            },
            {
                "key": "planner",
                "name": "Planner",
                "status": _stage_status(bool(planned)),
                "summary": (
                    f"{len(planned)} seeded · {len(tools_for(decision.intent))} tools offered"
                    if planned
                    else f"{len(tools_for(decision.intent))} tools offered, none seeded"
                ),
                "detail": {
                    "seeded": [{"tool": c.name, "args": c.args} for c in planned],
                    "offered": [t["name"] for t in tools_for(decision.intent)],
                },
            },
            {
                "key": "tools",
                "name": "Tool loop",
                "status": _stage_status(bool(response.trace), bool(errored)),
                "summary": (
                    f"{len(response.trace)} call(s), {len(errored)} failed"
                    if response.trace
                    else "no tools called"
                ),
                "detail": {
                    "calls": [
                        {
                            "tool": e.tool,
                            "args": e.args,
                            "ms": e.ms,
                            "error": e.error,
                            "result": _truncate(e.result),
                        }
                        for e in response.trace
                    ]
                },
            },
            {
                "key": "verifier",
                "name": "Verifier",
                "status": "ok" if verification.ok else "failed",
                "summary": verification.summary(),
                "detail": {
                    "ok": verification.ok,
                    "claims": [
                        {
                            "kind": c.kind,
                            "value": c.value,
                            "supported": c.supported,
                            "source": c.source_tool,
                        }
                        for c in verification.claims
                    ],
                    "notes": verification.notes,
                    "evidence": {
                        "identifiers": sorted(evidence.identifiers),
                        "numbers": len(evidence.numbers),
                    },
                },
            },
            {
                "key": "explainer",
                "name": "Explainer",
                "status": _stage_status(bool(response.narrative), LLM_KIND != "ollama"),
                "summary": (
                    "model-polished" if LLM_KIND == "ollama"
                    else "template renderer (no model configured)"
                ),
                "detail": {"narrative": response.narrative},
            },
        ],
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "entities": entities.to_dict(),
        "response": response.to_dict(),
        "narrative": response.narrative,
        "citations": [{"kind": c.kind, "id": c.id} for c in response.citations],
        "unknowns": response.unknowns,
    }


def _truncate(value: Any, limit: int = 4000) -> Any:
    """Keep a runaway lookup from flooding the panel."""
    if value is None:
        return None
    text = json.dumps(value, default=str)
    if len(text) <= limit:
        return value
    if isinstance(value, list):
        return {"_truncated": f"{len(value)} rows", "sample": value[:5]}
    return {"_truncated": f"{len(text)} chars"}


def build_state() -> dict[str, Any]:
    """What is real and what is a stub. The main thing you are here to check."""
    _, llm_label, port, port_label = backends()
    tools = []
    for name in sorted(TOOL_NAMES):
        try:
            getattr(port, name)(**_probe_args(name))
            live = True
        except Exception:
            live = False
        tools.append({"name": name, "live": live})

    return {
        "llm": {"live": LLM_KIND == "ollama" and "unreachable" not in llm_label,
                "model": llm_label},
        "data": {"live": "postgres" in port_label, "source": port_label},
        "tools": tools,
        "dataset": {
            "present": config.DATA_DIR.exists(),
            "exemplars": len(load_exemplars()),
        },
        "intents": [str(i) for i in Intent],
        "tool_schemas": TOOL_SCHEMAS,
    }


def _probe_args(name: str) -> dict[str, Any]:
    return {
        "lookup": {"entity": "crew", "filters": {"base": "BLR"}},
        "explain_rule": {"rule_id": "RULE-DUTY-02"},
        "duty_clock": {"crew_id": "C-1042"},
        "check_legality": {"crew_id": "C-1042", "pairing_id": "P-2291"},
        "find_options": {"pairing_id": "P-2291", "role": "Captain"},
        "ripple": {"event": {}},
        "simulate": {"event": {}},
        "joint_plan": {"events": []},
    }[name]


def scenario_index() -> list[dict[str, Any]]:
    """S1-S6 for the scenario feed, straight from the generated fixtures."""
    path = config.REPO_ROOT / "evals" / "fixtures" / "index.json"
    return json.loads(path.read_text()) if path.exists() else []


def scenario_detail(scenario_id: str) -> dict[str, Any]:
    path = config.REPO_ROOT / "evals" / "fixtures" / f"{scenario_id.upper()}.json"
    if not path.exists():
        return {"error": {"code": "UNRESOLVED_ENTITY",
                          "message": f"no scenario {scenario_id!r}",
                          "hint": "GET /api/v1/scenarios"}}
    return json.loads(path.read_text())


def gold_questions() -> list[dict[str, Any]]:
    """The 38 gold prompts, with the tier our router assigns each one."""
    return [
        {
            "id": e.question_id,
            "tier": e.tier,
            "prompt": e.prompt,
            "routed_tier": int(route(e.prompt).tier),
            "intent": str(route(e.prompt).intent),
        }
        for e in load_exemplars()
    ]


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write(f"  {args[0]}\n")

    def _cors(self) -> None:
        """Angular dev-serves on :4200 and this listens on :8420, so without
        these the browser blocks every call before it leaves the page."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    @staticmethod
    def _canonical(path: str) -> str:
        """Accept the contract's /api/v1 paths as well as the short ones."""
        return path.replace("/api/v1/", "/api/", 1) if path.startswith("/api/v1/") else path

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self._canonical(urlparse(self.path).path)

        if path == "/api/state":
            return self._send_json(build_state())
        if path == "/api/health":
            state = build_state()
            return self._send_json({
                "ok": True, "model": state["llm"]["model"],
                "data": state["data"]["source"],
                "tools_live": sum(t["live"] for t in state["tools"]),
                "tools_total": len(state["tools"]),
            })
        if path == "/api/rules":
            from agent.tools import dispatch
            _, _, port, _ = backends()
            rules = [dispatch(port, "explain_rule", {"rule_id": r}).result
                     for r in config.ALL_RULE_IDS]
            return self._send_json([r for r in rules if r])
        if path == "/api/scenarios":
            return self._send_json(scenario_index())
        if path.startswith("/api/scenarios/"):
            return self._send_json(scenario_detail(path.rsplit("/", 1)[-1]))
        if path == "/api/questions":
            return self._send_json(gold_questions())
        if path == "/api/stream":
            return self._stream(parse_qs(urlparse(self.path).query).get("q", [""])[0])

        return super().do_GET()

    def do_POST(self) -> None:
        if self._canonical(urlparse(self.path).path) != "/api/ask":
            return self._send_json(
                {"error": {"code": "UNRESOLVED_ENTITY",
                           "message": f"no route {self.path!r}",
                           "hint": "POST /api/v1/ask"}}, 404)

        length = int(self.headers.get("Content-Length", 0))
        try:
            query = json.loads(self.rfile.read(length) or b"{}").get("query", "").strip()
        except json.JSONDecodeError:
            return self._send_json({"error": "malformed JSON"}, 400)

        if not query:
            return self._send_json(
                {"error": {"code": "AMBIGUOUS_QUERY", "message": "empty query",
                           "hint": "send {\"query\": \"...\"}"}}, 400)

        try:
            return self._send_json(run_pipeline(query))
        except Exception:
            traceback.print_exc()
            return self._send_json(
                {"error": {"code": "INTERNAL", "message": "pipeline raised",
                           "hint": traceback.format_exc()[-400:]}}, 500
            )

    def _stream(self, query: str) -> None:  # noqa: D401
        """SSE, in the shape `docs/API_CONTRACT.md` specifies.

        Here so Kiran can see the real event sequence before `api/` exists.
        """
        if not query:
            return self._send_json({"error": "missing q"}, 400)

        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        try:
            for event in Advisor().stream(query):
                payload = json.dumps(event.data, default=str)
                self.wfile.write(f"event: {event.event}\ndata: {payload}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    state = build_state()
    live = sum(t["live"] for t in state["tools"])

    print(f"\n  dCortex agent console   http://localhost:{PORT}")
    print(f"  model  {state['llm']['model']}")
    print(f"  data   {state['data']['source']}")
    print(f"  tools  {live}/{len(state['tools'])} live · "
          f"{state['dataset']['exemplars']} gold questions")
    print("  ctrl-c to stop\n")

    try:
        server = Server(("127.0.0.1", PORT), Handler)
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        print(f"  port {PORT} is already in use — another console is running.\n")
        print(f"  stop it with:  lsof -ti:{PORT} | xargs kill\n")
        return 1

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
