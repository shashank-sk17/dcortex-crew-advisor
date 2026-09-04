"""dCortex Crew Ops Advisor — the agent layer (L3).

    ROUTER -> PLANNER -> TOOL LOOP -> VERIFIER -> EXPLAINER

One agent with tools. The model selects, sequences and narrates; it never
calculates. Everything below `agent.tools.ToolPort` is deterministic Python.

No network calls are made anywhere in this package. `agent.llm.PlaceholderLLM`
returns canned responses so the whole pipeline runs and every test passes with
no API key and no SDK. See `agent/README.md`.
"""

from agent.advisor import Advisor, AdvisorConfig
from agent.entities import Entities, extract, mask
from agent.router import Route, route
from agent.schemas import AdvisorResponse, Intent, Option, RuleVerdict, Tier
from agent.tools import PlaceholderToolPort, ToolPort
from agent.verifier import verify

__all__ = [
    "Advisor",
    "AdvisorConfig",
    "AdvisorResponse",
    "Entities",
    "Intent",
    "Option",
    "PlaceholderToolPort",
    "Route",
    "RuleVerdict",
    "Tier",
    "ToolPort",
    "extract",
    "mask",
    "route",
    "verify",
]
