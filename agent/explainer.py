"""Answer object -> controller prose.

Templates first, model second. The deterministic renderer below produces a
correct, citable answer with no model in the loop at all, which means the
system degrades to "terse but accurate" rather than to "broken" when the
model is unavailable — and it gives the verifier something to check even on
the placeholder path.

When a real client is wired up, `polish()` rewrites the template output into
something a controller would actually say. It may reword; it may not
introduce a fact, and the verifier runs after it to enforce that.
"""

from __future__ import annotations

from agent import config
from agent.llm import LLM
from agent.schemas import (
    AdvisorResponse,
    Citation,
    ConsequenceAnswer,
    LookupAnswer,
    Option,
    ReplacementAnswer,
    RuleVerdict,
    Verdict,
)


def _inr(amount: int) -> str:
    return f"₹{amount:,}"


def _hours(value: float) -> str:
    """3.0 -> '3h'; 1.33 -> '1h20m'. Matches how the answer keys read."""
    whole = int(value)
    minutes = round((value - whole) * 60)
    if minutes == 60:
        whole, minutes = whole + 1, 0
    return f"{whole}h{minutes:02d}m" if minutes else f"{whole}h"


# --------------------------------------------------------------------------
# Rule verdicts
# --------------------------------------------------------------------------


def render_verdict(v: RuleVerdict) -> str:
    head = f"{v.rule_id}  {v.status}"
    if v.detail:
        return f"{head} — {v.detail}"
    if v.used is not None and v.limit is not None:
        return f"{head} — {v.used} / {v.limit}"
    return head


def render_verdicts(verdicts: list[RuleVerdict]) -> str:
    if not verdicts:
        return ""
    failures = [v for v in verdicts if v.failed]
    lines = [render_verdict(v) for v in (failures or verdicts)]
    header = "Blocking:" if failures else f"All {len(verdicts)} rules pass:"
    return header + "\n" + "\n".join(f"  {line}" for line in lines)


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------


def render_option(option: Option, show_rank: bool = True) -> str:
    prefix = f"#{option.rank} " if show_rank and option.rank else ""
    parts = [f"{prefix}{option.action}", _inr(option.cost_inr)]

    if option.delay_hours:
        parts.append(f"{_hours(option.delay_hours)} delay")
    if option.blast_radius:
        parts.append(f"blast radius {option.blast_radius}")
    if not option.legal:
        blocking = [v.rule_id for v in option.verdicts if v.failed]
        parts.append("ILLEGAL" + (f" ({', '.join(blocking)})" if blocking else ""))
    if option.unlock:
        parts.append(f"unlocks if {option.unlock}")

    return " · ".join(parts)


# --------------------------------------------------------------------------
# Per-tier narratives
# --------------------------------------------------------------------------


def render_lookup(answer: LookupAnswer) -> str:
    if not answer.rows:
        return "No records match that query."
    noun = "record" if answer.count == 1 else "records"
    lines = [f"{answer.count} {noun}."]
    for row in answer.rows[:10]:
        lines.append("  " + ", ".join(f"{k}={v}" for k, v in row.items()))
    if answer.count > 10:
        lines.append(f"  … and {answer.count - 10} more.")
    return "\n".join(lines)


def render_replacement(answer: ReplacementAnswer) -> str:
    lines: list[str] = []

    if answer.uncovered_flights:
        lines.append(
            f"{len(answer.uncovered_flights)} flight(s) uncrewed: "
            + ", ".join(answer.uncovered_flights)
        )
    if answer.at_risk_flights:
        lines.append(
            f"{len(answer.at_risk_flights)} downstream at risk: "
            + ", ".join(answer.at_risk_flights)
        )
    if answer.passengers_affected:
        lines.append(f"{answer.passengers_affected} passengers affected.")

    if answer.funnel:
        trail = " → ".join(str(stage.count) for stage in answer.funnel)
        lines.append(f"\nCandidates: {trail}")
        for stage in answer.funnel:
            if stage.dropped:
                lines.append(f"  −{stage.dropped} {stage.stage}: {stage.reason}")

    if answer.options:
        lines.append("\nLegal options:")
        lines += [f"  {render_option(o)}" for o in answer.options]
    elif not answer.near_misses:
        lines.append("\nNo legal option found.")

    if answer.near_misses:
        lines.append("\nNear misses — not legal now, but reachable:")
        lines += [f"  {render_option(o, show_rank=False)}" for o in answer.near_misses]

    return "\n".join(lines)


def render_consequence(answer: ConsequenceAnswer) -> str:
    lines: list[str] = []

    if answer.joint_plan:
        plan = answer.joint_plan
        total = plan.get("total_cost_inr")
        if total is not None:
            lines.append(f"Optimal joint plan — {_inr(int(total))} total.")
        for key, value in plan.items():
            if key.startswith("assign") and isinstance(value, dict):
                lines.append(f"  {key}: {value.get('action', '')}")
        if (alts := plan.get("equal_cost_alternatives")) and int(alts) > 1:
            lines.append(
                f"  {int(alts) - 1} other assignments cost exactly the same — "
                "this is one of several equally correct plans."
            )

    if answer.options:
        lines.append("\nRanked options:")
        lines += [f"  {render_option(o)}" for o in answer.options]

    if br := answer.blast_radius:
        lines.append(
            f"\nBlast radius: {br.nodes} nodes · {br.flights} flights · "
            f"{br.aircraft} aircraft · {br.passengers} passengers"
        )

    if answer.world_diff and (changed := answer.world_diff.get("changed")):
        lines.append(f"\n{len(changed)} change(s) versus the base world.")

    return "\n".join(lines)


def render(response: AdvisorResponse) -> str:
    """Deterministic prose for any answer body. No model involved."""
    match response.answer:
        case LookupAnswer() as a:
            return render_lookup(a)
        case ReplacementAnswer() as a:
            return render_replacement(a)
        case ConsequenceAnswer() as a:
            return render_consequence(a)
        case _:
            return "No answer produced."


# --------------------------------------------------------------------------
# Citations
# --------------------------------------------------------------------------


def collect_citations(response: AdvisorResponse) -> list[Citation]:
    """Every rule and record the answer leans on, deduplicated."""
    seen: set[tuple[str, str]] = set()
    citations: list[Citation] = []

    def add(kind: str, ident: str, source: str | None = None) -> None:
        if (kind, ident) not in seen:
            seen.add((kind, ident))
            citations.append(Citation(kind=kind, id=ident, source=source))

    options: list[Option] = []
    if isinstance(response.answer, (ReplacementAnswer, ConsequenceAnswer)):
        options = list(response.answer.options)
    if isinstance(response.answer, ReplacementAnswer):
        options += response.answer.near_misses

    for option in options:
        for rule_id in option.rules_checked:
            add("rule", rule_id)
        for verdict in option.verdicts:
            add("rule", verdict.rule_id)
        if option.crew_id:
            add("record", option.crew_id, "crew.json")

    for entry in response.trace:
        if entry.tool == "explain_rule" and (rid := entry.args.get("rule_id")):
            add("rule", str(rid))

    return citations


# --------------------------------------------------------------------------
# Optional model pass
# --------------------------------------------------------------------------

POLISH_INSTRUCTIONS = """\
You are writing for an airline crew controller under time pressure.

Rewrite the structured summary below as you would say it to them: lead with
the recommendation, then why, then what it costs and what it breaks. Cite rule
ids inline where they decided something.

Absolute constraint: you may reword, reorder and compress. You may NOT add any
identifier, number, name or claim that is not already present. If something is
missing, leave it missing — a verifier will reject this answer otherwise.
"""


def polish(response: AdvisorResponse, llm: LLM | None = None) -> str:
    """Rewrite template output into controller language.

    Falls back to the template verbatim when no model is configured, which is
    the current default — the placeholder client returns no usable prose.
    """
    template = render(response)
    if llm is None:
        return template

    result = llm.complete(
        system=POLISH_INSTRUCTIONS,
        messages=[{"role": "user", "content": template}],
        model=config.EXPLAINER_MODEL,
        max_tokens=1024,
    )
    text = (result.text or "").strip()
    if not text or text.startswith("[placeholder]"):
        return template
    return text
