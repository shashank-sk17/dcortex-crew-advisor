"""Command-line harness for the agent.

    python -m agent.cli "Who is on reserve at BLR on 2026-09-15?"
    python -m agent.cli --route-only "Both captains are sick, give a joint plan"
    python -m agent.cli --stream  "What does RULE-DUTY-02 say?"
    python -m agent.cli --entities "Can C-1042 cover P-2291 on 15 Sep?"

No API key needed — the placeholder client drives the loop.
"""

from __future__ import annotations

import argparse
import json
import sys

from agent.advisor import Advisor
from agent.entities import extract, mask
from agent.router import route


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.cli", description=__doc__)
    parser.add_argument("query", nargs="+", help="the controller's question")
    parser.add_argument("--route-only", action="store_true", help="classify and stop")
    parser.add_argument("--entities", action="store_true", help="extract entities and stop")
    parser.add_argument("--stream", action="store_true", help="emit SSE-shaped events")
    parser.add_argument("--json", action="store_true", help="raw response object")
    args = parser.parse_args(argv)

    query = " ".join(args.query)

    if args.entities:
        print(json.dumps(extract(query).to_dict(), indent=2))
        print(f"\nmasked: {mask(query)}")
        return 0

    if args.route_only:
        print(json.dumps(route(query).to_dict(), indent=2))
        return 0

    advisor = Advisor()

    if args.stream:
        for event in advisor.stream(query):
            print(f"event: {event.event}")
            print(f"data:  {json.dumps(event.data, default=str)[:400]}\n")
        return 0

    response = advisor.ask(query)

    if args.json:
        print(json.dumps(response.to_dict(), indent=2, default=str))
        return 0

    print(f"tier {int(response.tier)} · {response.intent} · {response.confidence}")
    print(f"entities: {response.entities}")
    print("-" * 66)
    print(response.narrative)
    if response.citations:
        print("-" * 66)
        print("cited: " + ", ".join(f"{c.kind}:{c.id}" for c in response.citations))
    if response.unknowns:
        print("-" * 66)
        for note in response.unknowns:
            print(f"! {note}")
    print("-" * 66)
    for entry in response.trace:
        status = entry.error or f"{entry.ms}ms"
        print(f"  {entry.tool}({entry.args}) -> {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
