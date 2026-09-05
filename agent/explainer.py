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

import datetime as dt
from decimal import Decimal
from typing import Any

from agent import config
from agent.llm import LLM
from agent.schemas import (
    AdvisorResponse,
    Intent,
    Citation,
    ConsequenceAnswer,
    LookupAnswer,
    NotificationAnswer,
    Option,
    ReplacementAnswer,
    RuleVerdict,
    Verdict,
)


ROW_LIMIT = 25
"""Rows shown before a lookup listing is truncated.

Ten cut Q01 short: BLR carries twelve reserves and the answer key lists all
twelve, so the correct answer was being truncated into an incomplete one.
Twenty-five clears every tier-1 gold answer with room over, and a table that
long is still quicker to read than the paragraph it replaced.
"""


def fmt_value(value: Any) -> str:
    """Render a backend value as a controller would read it.

    Postgres hands back `datetime.date`, `time` and `Decimal` objects, and
    Python's repr of a list of dates is `[datetime.date(2026, 9, 14), ...]`.
    That is unreadable, and the verifier then lifts `2026`, `14`, `15` out of
    it as unsourced numeric claims. ISO strings fix both.
    """
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"
    if isinstance(value, (list, tuple)):
        return ", ".join(fmt_value(v) for v in value)
    if isinstance(value, dict):
        return " ".join(f"{k}={fmt_value(v)}" for k, v in value.items())
    return str(value)


def who(crew_id: str | None, name: str | None = None,
        rank: str | None = None) -> str:
    """How a crew member is written, everywhere, without exception.

    `Captain A. Nair (C-1042)` — the person first, because that is who the
    controller phones, and the id in brackets because that is what goes into
    the roster system and two people can share a surname. Falling back to the
    bare id when no name is loaded is correct; inventing one is not.
    """
    if not crew_id:
        return ""
    label = " ".join(str(part) for part in (rank, name) if part)
    return f"{label} ({crew_id})" if label else crew_id


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

    if option.reachability_minutes is not None:
        parts.append(f"reachable in {option.reachability_minutes} min")

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


# Columns a controller reads first. Anything not named here keeps its natural
# order behind these — a stable left edge is what makes a table scannable when
# you are reading it for the third time in ten minutes.
_COLUMN_ORDER: tuple[str, ...] = (
    "crew_id", "name", "rank", "role", "base",
    "flight_id", "flight_no", "pairing_id", "aircraft", "aircraft_type",
    "date", "dep_station", "arr_station", "dep_utc", "arr_utc",
    "oncall_start_utc", "oncall_end_utc", "report_utc", "release_utc",
    "cert_type", "valid_from", "valid_to",
)


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    """Union of the rows' keys, preferred columns first.

    A union rather than the first row's keys: backends differ in which
    optional fields they populate, and a column silently missing because row
    one happened to lack it is a fact withheld from the controller.
    """
    seen: list[str] = []
    for row in rows:
        for key in row:
            if key not in seen:
                seen.append(key)
    ranked = [c for c in _COLUMN_ORDER if c in seen]
    return ranked + [c for c in seen if c not in ranked]


def render_lookup(answer: LookupAnswer) -> str:
    """A tier-1 result as an aligned table.

    This is the tier a controller reaches first and the one dCortex makes
    mandatory, so it is worth reading well. `key=value · key=value` repeated
    the column name on every row and put the values at a different offset in
    each one, which is unscannable at exactly the moment scanning matters.

    Values are never truncated. A shortened id reads as a different id, and
    the verifier would rightly refuse to source it.
    """
    if not answer.rows:
        return "No records match that query."

    noun = "record" if answer.count == 1 else "records"
    shown = answer.rows[:ROW_LIMIT]

    # Rows of different shapes are different questions, and interleaving them
    # produces a table that is mostly blank cells — a roster lookup returning
    # crew *and* duty days rendered six names against two dates with nothing
    # lining up. Group by shape and give each its own table.
    groups: list[list[dict[str, Any]]] = []
    signatures: list[tuple[str, ...]] = []
    for row in shown:
        signature = tuple(sorted(row))
        if signature in signatures:
            groups[signatures.index(signature)].append(row)
        else:
            signatures.append(signature)
            groups.append([row])

    lines = [f"{answer.count} {noun}."]
    for group in groups:
        lines.extend(_table(group))
    if answer.count > ROW_LIMIT:
        # No number here on purpose. "and N more" is arithmetic the renderer
        # did itself, and even a literal page size is a figure no tool
        # produced — the verifier rejects both, correctly. The total above is
        # sourced: it is the length of the tool's own result.
        lines.append("  (list truncated)")
    return "\n".join(lines)


def _table(shown: list[dict[str, Any]]) -> list[str]:
    """One aligned table for one set of same-shaped rows."""
    columns = _columns(shown)

    # A column holding one value across every row discriminates nothing here,
    # and `dates` on the reserve pool is 82 characters of it — enough to push
    # the on-call windows off the side of the screen. State it once above the
    # table instead. Stated, not dropped: the value is still on the page.
    constant: list[str] = []
    if len(shown) > 1:
        for column in list(columns):
            values = {fmt_value(row.get(column, "")) for row in shown}
            if len(values) == 1 and len(next(iter(values))) > 20:
                constant.append(f"{column}: {values.pop()}")
                columns.remove(column)

    cells = [[fmt_value(row.get(c, "")) for c in columns] for row in shown]
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(columns)]

    def line(values: list[str]) -> str:
        padded = [v.ljust(w) for v, w in zip(values, widths)]
        return "  " + "  ".join(padded).rstrip()

    lines = [f"  every row — {c}" for c in constant]
    lines += ["", line(columns), "  " + "  ".join("─" * w for w in widths)]
    lines += [line(row) for row in cells]
    return lines


def render_replacement(answer: ReplacementAnswer) -> str:
    """Lead with the recommendation; the ranking is support, not the answer.

    A controller under pressure needs to know what to do, then why. A ranked
    table makes them do the deciding, which is the work we were meant to save.
    """
    lines: list[str] = []

    if answer.verdicts:
        subject = who(answer.subject, answer.subject_name,
                      answer.subject_rank) or "That assignment"
        blocking = [v for v in answer.verdicts if v.failed]
        if blocking:
            lines.append(f"▸ {subject} would breach "
                         f"{len(blocking)} rule{'s' if len(blocking) > 1 else ''}:")
            lines += [f"  {render_verdict(v)}" for v in blocking]
        else:
            lines.append(f"▸ {subject} is legal — all "
                         f"{len(answer.verdicts)} rules pass.")
            lines += [f"  {render_verdict(v)}" for v in answer.verdicts]
        if not answer.options:
            return "\n".join(lines)
        lines.append("")

    if rec := answer.recommended:
        head = f"▸ {rec.action} — {_inr(rec.cost_inr)}"
        if rec.delay_hours:
            head += f", {_hours(rec.delay_hours)} delay"
        else:
            head += ", no delay"
        lines.append(head)

        if answer.equal_cost_alternatives:
            n = answer.equal_cost_alternatives
            lines.append(f"  ({n} other option{'s' if n > 1 else ''} cost the same "
                         f"— this is not a uniquely correct choice.)")
        if rec.rules_checked:
            lines.append(f"  Clears all {len(rec.rules_checked)} rules.")
        lines.append("")

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

    if answer.options:
        crewed = [o for o in answer.options if o.crew_id]
        cancel = next((o for o in answer.options if not o.crew_id), None)
        alternatives = [o for o in crewed if o is not answer.recommended
                        and o.crew_id != (answer.recommended.crew_id
                                          if answer.recommended else None)]

        if alternatives:
            lines.append("\nAlternatives:")
            lines += [f"  {render_option(o)}" for o in alternatives]
            if answer.next_tier_premium_inr:
                lines.append(f"  ({_inr(answer.next_tier_premium_inr)} more "
                             f"than the recommended option.)")

        if cancel:
            # The contrast, not a row. Cancellation is an order of magnitude
            # above everything else, and that gap is the argument a controller
            # takes to their manager.
            lines.append(f"\nAgainst cancelling: {_inr(cancel.cost_inr)}")
            if answer.cancellation_multiple:
                lines.append(f"  {answer.cancellation_multiple}× the recommended option. "
                             f"Even the deadhead is far cheaper than cancelling.")
    elif not answer.near_misses and answer.funnel:
        # Only claim this when a search actually ran. Saying "no legal option"
        # because the search tool is missing asserts something about the world
        # that we never checked.
        lines.append("\nNo legal option found.")

    if answer.near_misses:
        lines.append("\nNear misses — not legal now, but reachable:")
        lines += [f"  {render_option(o, show_rank=False)}" for o in answer.near_misses]

    # Evidence last: the controller acts on the recommendation, and audits the
    # funnel only if they want to challenge it.
    if answer.funnel:
        considered = answer.funnel[0].count
        legal = answer.funnel[-1].count
        lines.append(f"\nConsidered {considered}, {legal} legal:")
        for stage in answer.funnel:
            if stage.dropped:
                lines.append(f"  −{stage.dropped} {stage.stage}: {stage.reason}")

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


def has_content(answer: Any) -> bool:
    """Whether the answer object actually carries a finding.

    An empty body means every tool failed, so the only thing to say is what
    went wrong — and that is the tools' own words, not the model's.
    """
    match answer:
        case LookupAnswer() as a:
            return bool(a.rows)
        case ReplacementAnswer() as a:
            return bool(a.options or a.near_misses or a.uncovered_flights
                        or a.funnel or a.verdicts)
        case ConsequenceAnswer() as a:
            return bool(a.options or a.blast_radius or a.world_diff or a.joint_plan)
    return False


def render_unavailable(response: AdvisorResponse) -> str:
    """What to say when the tools that would answer this did not run.

    A blank answer, or worse a confident "no legal option found", both misread
    a missing capability as a fact about the world. Name the gap instead.
    """
    failed = [e for e in response.trace if e.error]
    if not failed:
        return "No data was returned for this question."

    # A NEEDS_CONFIRMATION or UNRESOLVED_ENTITY error is about the *question*,
    # not about our capability — it already reads as an answer, so lead with it
    # verbatim rather than burying it under a header about missing tools.
    about_the_query = [e for e in failed
                       if e.error.startswith(("NEEDS_CONFIRMATION",
                                              "UNRESOLVED_ENTITY",
                                              "AMBIGUOUS_QUERY"))]
    if about_the_query:
        seen: list[str] = []
        for entry in about_the_query:
            detail = entry.error.split(":", 1)[-1].strip()
            if detail not in seen:
                seen.append(detail)
        return "\n\n".join(seen)

    lines = ["Cannot answer this yet — the tools it needs are unavailable:"]
    for entry in failed:
        detail = entry.error.split(":", 1)[-1].strip()
        lines.append(f"  {entry.tool}: {detail}")
    lines.append("\nThis is a missing capability, not a finding about the operation.")
    return "\n".join(lines)


def render(response: AdvisorResponse) -> str:
    """Deterministic prose for any answer body. No model involved."""
    match response.answer:
        case LookupAnswer() as a:
            body = render_lookup(a) if a.rows else ""
        case ReplacementAnswer() as a:
            body = render_replacement(a)
        case ConsequenceAnswer() as a:
            body = render_consequence(a)
        case NotificationAnswer() as a:
            # Already prose, and every time in it came from the roster. There
            # is nothing for a second renderer to add.
            body = a.message
        case _:
            body = ""

    return body.strip() or render_unavailable(response)


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

LOOKUP_INSTRUCTIONS = """\
You are answering an airline crew controller's factual question.

Below is a question and the rows the tools returned for it. Answer the
question in one short paragraph, in plain language, using only those rows.

Rules, in order of importance:

1. Every name, id, number, date and status you write must appear in the rows.
   Invent nothing. If the rows do not answer part of the question, say that
   part is not in the data.
2. Do NOT recommend anything, do NOT infer a situation, do NOT describe a
   problem. Nothing here is a disruption; it is a record. "Reduce their duty
   hours" is not an answer to "who is this".
3. Name every crew member as `Rank Name (C-XXXX)` the first time they appear
   — "Captain A. Nair (C-1042)" — and by name after that. Never a bare id: a
   controller phones a person. Never a name without the id somewhere: the id
   is what goes into the roster system.
4. Do not assign a gender. The records hold an initial and a surname and
   nothing else, so write the name, the rank, or "they".
5. Lead with what was asked. Mention what a controller would want next only
   if it is in the rows — current pairing, duty headroom, anything expiring.
6. No preamble, no "based on the data provided". Two to five sentences.
"""


POLISH_INSTRUCTIONS = """\
You are writing for an airline crew controller under time pressure.

Rewrite the structured summary below as you would say it to them: lead with
the recommendation, then why, then what it costs and what it breaks. Cite rule
ids inline where they decided something.

Name every crew member as `Rank Name (C-XXXX)` the first time they appear —
"Captain A. Nair (C-1042)" — and by name after that. Never a bare id, and
never a name without its id somewhere. Do not assign a gender: the records
hold an initial and a surname, so use the name, the rank, or "they".

Absolute constraint: you may reword, reorder and compress. You may NOT add any
identifier, number, name or claim that is not already present. If something is
missing, leave it missing — a verifier will reject this answer otherwise.
"""


def polish(response: AdvisorResponse, llm: LLM | None = None) -> str:
    """Rewrite template output into controller language.

    Falls back to the template verbatim when no model is configured, which is
    the current default — the placeholder client returns no usable prose.

    Tier 1 gets its own instructions rather than the recommendation ones, and
    keeps its tables underneath the prose.

    It used to get no model pass at all. That was right when a lookup meant
    one small table and the model was llama3.1:8b — asked "what does
    RULE-DUTY-02 say?" it produced "Recommendation: reduce the crew's duty
    hours — the crew has exceeded the maximum allowed", an entire fabricated
    situation with no crew and nothing exceeded, and the verifier passed it
    because the invention was narrative rather than numeric.

    What changed is the question. "Who is C-1042" now fans out to nine tool
    calls across seven entities, and the template answers it with "16
    records." followed by seven tables — every fact present and the question
    unanswered. A controller cannot read that at 05:00.

    So the ban is replaced by four narrower defences, because the risk it was
    guarding against is real: LOOKUP_INSTRUCTIONS forbids recommending or
    inferring a situation, the tables stay below the prose as evidence, an
    answer carrying no rows is still never polished, and EXPLAIN_RULE — the
    shape that produced that fabrication — is still never polished either.
    """
    template = render(response)
    if llm is None:
        return template

    if isinstance(response.answer, LookupAnswer):
        # Two lookups still get no model pass. An empty one has only the
        # tools' own error text to offer, and EXPLAIN_RULE is the exact shape
        # that produced the llama3.1 fabrication above: the rule text *is* the
        # answer, so summarising it can only drift from the regulation.
        if not response.answer.rows or response.intent is Intent.EXPLAIN_RULE:
            return template
        result = llm.complete(
            system=LOOKUP_INSTRUCTIONS,
            messages=[{"role": "user", "content":
                       f"Question: {response.query}\n\n{template}"}],
            model=config.EXPLAINER_MODEL,
            max_tokens=512,
        )
        text = (result.text or "").strip()
        if not text or text.startswith("[placeholder]"):
            return template
        return f"{text}\n\n{template}"

    # Never paraphrase a tool failure. The error text is already written for a
    # controller and often carries the only actionable content — "there is no
    # crew C-1045, did you mean C-1042?" — so rewriting it can only lose or
    # distort that.
    #
    # Asked about C-1045, the model reported "C-1045 isn't rostered on any
    # pairing this week" (the tool said no such crew exists), claimed ripple
    # needed a crew_id that had been supplied, and dropped the C-1042
    # suggestion entirely. The verifier passed all of it: the invention was
    # narrative, so it contained no number or identifier to check.
    if not has_content(response.answer):
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
