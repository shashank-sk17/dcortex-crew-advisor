"""Prompt assembly.

The system prompt is long, static and hit on every turn, so it is built once
and cached in-process. When a real client lands it should also be marked as a
cache breakpoint on the wire.

Exemplars are inlined rather than retrieved: the full corpus is 776 tokens, so
the model sees all 38 instead of a top-3 approximation (DECISIONS.md #15).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from agent.schemas import Intent

PROMPT_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=8)
def _read(name: str) -> str:
    path = PROMPT_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


@lru_cache(maxsize=2)
def base_system_prompt(with_exemplars: bool = False) -> str:
    """Role, constraints and the rulebook.

    Exemplars are **off by default**. They exist to help classify an intent,
    and the router classifies 38/38 without a model at all — so shipping them
    on every tool-loop call spent 836 of 2,250 input tokens on context the
    advisor never reads. On Groq's free tier that is the difference between
    three and five calls a minute.

    The router's own fallback path asks for them explicitly.
    """
    from agent.exemplars import exemplar_block

    parts = [_read("system.md")]
    if with_exemplars and (block := exemplar_block()):
        parts.append(
            "\n## Worked examples\n\nIdentifiers are masked; these show the "
            "*shape* of each tier, not specific answers.\n" + block
        )
    return "\n".join(p for p in parts if p).strip()


def naming_rule() -> str:
    """The `Rank Name (C-XXXX)` section, lifted out of the system prompt.

    The explainer runs its own passes with their own instructions, and those
    models need this rule too. Quoting it here rather than restating it means
    there is one wording to change, and no way for the two to drift into
    disagreeing about how a person is written.
    """
    body = _read("system.md")
    start = body.find("## How to refer to people")
    if start < 0:
        return ""
    end = body.find("\n## ", start + 1)
    return body[start:end if end > 0 else len(body)].strip()


@lru_cache(maxsize=32)
def system_prompt(intent: Intent | None = None, with_exemplars: bool = False) -> str:
    """Base prompt plus a short note on what this intent has to produce."""
    prompt = base_system_prompt(with_exemplars)
    if intent is None:
        return prompt
    if guidance := INTENT_GUIDANCE.get(intent):
        prompt += f"\n\n## This request\n\n{guidance.strip()}\n"
    return prompt


INTENT_GUIDANCE: dict[Intent, str] = {
    Intent.LOOKUP_DUTY_CLOCK: """
Report accrued hours *and* remaining headroom against the limit. A controller
needs to know how much room is left, not just what has been used.
""",
    Intent.CHECK_LEGALITY: """
State the verdict first, then every rule that decided it with its numbers.
If it fails, say by how much — "exceeds by 1h20m" is actionable, "illegal"
is not.
""",
    Intent.FIND_REPLACEMENT: """
Lead with the funnel: how many candidates existed and why each group dropped
out. Then the ranked legal options. If nothing is legal, that is not a dead
end — report near misses and what would unlock them.
""",
    Intent.IMPACT_OF_EVENT: """
Separate what is uncrewed *now* from what is at risk *downstream*. Crew fly
pairings, not legs: a multi-day pairing that loses its captain on day 1 also
strands day 2 wherever it overnights.
""",
    Intent.RANK_OPTIONS: """
Rank by cost and delay among legal options only. Always include the do-nothing
cost — cancellation is ₹250,000 per leg, which is what makes an expensive
deadhead look cheap. Name the trade-off explicitly.
""",
    Intent.SIMULATE_WHATIF: """
Compare the two worlds directly: what changes, what breaks, what it costs.
A delay can create a fresh crewing problem by pushing the rostered crew past
their FDP limit on the tail legs — check for that.
""",
    Intent.JOINT_PLAN: """
Solve both disruptions together, never one then the other. The same crew
member cannot cover two pairings at once.

Ties are normal and expected. When several assignments cost the same, say so
plainly — "three other allocations cost the same" — rather than presenting one
as uniquely correct.
""",
    Intent.RESOLVE_ILLEGAL: """
Name the breach, the rule and the date. Then resolve it: who can legally take
the duty, or what else has to change.
""",
}
