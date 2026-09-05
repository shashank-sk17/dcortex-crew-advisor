"""The trust gate.

Before any answer reaches a controller, every identifier and every number in
its prose must be traceable to something a tool actually returned. Anything
unsupported is a hallucination by definition, because the model has no other
source of facts.

This is what makes the demo credible, and it is deliberately not a language
model: it is set membership over the trace. Deterministic, fast, and it cannot
itself hallucinate.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from agent import config
from agent.entities import (
    AIRCRAFT_RE,
    CREW_RE,
    FLIGHT_ID_RE,
    FLIGHT_NO_RE,
    PAIRING_RE,
    RULE_RE,
)
from agent.schemas import TraceEntry

# Numbers as a controller would write them: 18,500 / ₹18500 / 61.33 / 1h20m
NUMBER_RE = re.compile(r"(?<![\w.])(?:₹\s*)?(\d[\d,]*(?:\.\d+)?)(?![\w])")

# Non-capturing so `findall` yields whole matches. A date is one claim, not
# three numbers — checking 2026-09-15 as "2026" + "09" + "15" both floods the
# ledger and lets a wrong date pass on the strength of its year.
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

# A whole ISO timestamp, matched before anything looks for a time inside it.
# It has to come out first: `2026-09-15T06:00:00+00:00` contains the report
# time *and* a UTC offset, and a pattern loose enough to see `06:00` through
# the `T` also reads `+00:00` as midnight. Pulling the timestamp out whole
# leaves one unambiguous time and no phantom.
ISO_DT_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)

# A time of day, once timestamps are out of the way. `\b` cannot open this:
# a bare time may be preceded by `-` in a range like `06:00-18:00`.
CLOCK_RE = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?Z?(?![\d:])")

def times_and_rest(text: str) -> tuple[list[str], str]:
    """Times of day named by any timestamps, and the text with them removed.

    Used on both sides of the gate so a report time is one fact whichever way
    it is written — Postgres hands back `2026-09-15T06:00:00+00:00`, a
    controller reads `06:00Z`, and the model turning one into the other is
    doing its job rather than inventing something.
    """
    found: list[str] = []
    for match in ISO_DT_RE.findall(text):
        stamp = match.split("T")[-1].split(" ")[-1]
        if norm := normalise_clock(stamp):
            found.append(norm)
    return found, ISO_DT_RE.sub(" ", text)


def normalise_clock(value: str) -> str | None:
    """`6:00`, `06:00Z`, `06:00:00+00:00` -> `06:00`. Anything else -> None.

    Seconds are dropped because no report or release time in this dataset
    carries them, and a trailing `:00` is a formatting artefact rather than a
    claim about the world.
    """
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?",
                         value.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), match.group(2)
    return f"{hour:02d}:{minute}" if hour < 24 else None


ID_PATTERNS = (
    CREW_RE, PAIRING_RE, FLIGHT_ID_RE, FLIGHT_NO_RE, RULE_RE, AIRCRAFT_RE,
    DATE_RE, CLOCK_RE,
)


@dataclass(slots=True)
class Claim:
    """One checkable assertion lifted out of the narrative."""

    kind: str          # "identifier" | "number"
    value: str
    supported: bool = False
    source_tool: str | None = None
    derivation: str | None = None
    """Set when the value was not returned by any tool but follows from two
    that were, e.g. "24000 - 18500". The claim is still auditable: a reader
    can check the arithmetic against numbers the tools did produce."""

    @property
    def status(self) -> str:
        if not self.supported:
            return "unsupported"
        return "derived" if self.derivation else "sourced"


@dataclass(slots=True)
class VerificationResult:
    ok: bool
    claims: list[Claim] = field(default_factory=list)
    unsupported: list[Claim] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    had_trace: bool = True

    @property
    def derived(self) -> list[Claim]:
        return [c for c in self.claims if c.derivation]

    def summary(self) -> str:
        if self.unsupported:
            bad = ", ".join(c.value for c in self.unsupported)
            return f"UNVERIFIED: {len(self.unsupported)} untraced claim(s): {bad}"
        if not self.had_trace:
            return "no tool ran — nothing in this answer has a source"
        if not self.claims:
            return "nothing asserted — no checkable claim was made"
        if derived := self.derived:
            return (f"verified: {len(self.claims)} claims — {len(derived)} derived "
                    f"by arithmetic from tool output, the rest returned directly")
        return f"verified: {len(self.claims)} claims all traced to tool output"


# --------------------------------------------------------------------------
# Building the evidence set
# --------------------------------------------------------------------------


def _walk(node: Any) -> Iterable[Any]:
    """Yield every scalar in an arbitrarily nested tool result.

    Collection lengths are yielded too. "12 records" is a count the explainer
    derived from what a tool returned, not a number the model invented, so the
    cardinality of every result is legitimate evidence.
    """
    if isinstance(node, dict):
        yield len(node)
        for key, value in node.items():
            yield key
            yield from _walk(value)
    elif isinstance(node, (list, tuple, set)):
        yield len(node)
        for item in node:
            yield from _walk(item)
    elif isinstance(node, (dt.date, dt.time, dt.datetime)):
        # Postgres returns these as objects, but the explainer prints them as
        # text. Index the rendered form or the narrative's own dates and times
        # look unsourced.
        yield str(node)
        yield node.isoformat()
    else:
        yield node


def _norm_number(raw: str) -> float | None:
    try:
        return float(raw.replace(",", "").replace("₹", "").strip())
    except ValueError:
        return None


def _strip_identifiers(text: str) -> str:
    """Blank out ids before scanning for numbers.

    Without this, "C-1042" contributes 1042 — which both invents a claim on
    the narrative side and, worse, would let a fabricated "1042 hours" pass
    verification on the evidence side.
    """
    for pattern in ID_PATTERNS:
        text = pattern.sub(" ", text)
    return text


def _numbers_in(text: str) -> list[float]:
    return [
        value
        for raw in NUMBER_RE.findall(_strip_identifiers(text))
        if (value := _norm_number(raw)) is not None
    ]


@dataclass(slots=True)
class Evidence:
    """Everything the tools actually said, indexed for membership tests."""

    identifiers: dict[str, str] = field(default_factory=dict)  # id -> tool
    numbers: list[tuple[float, str]] = field(default_factory=list)

    def has_identifier(self, value: str) -> str | None:
        if found := self.identifiers.get(value):
            return found
        # A time is the one identifier with several correct spellings.
        # `06:00Z` is what a controller reads and `2026-09-15T06:00:00+00:00`
        # is what Postgres returns; the model reformatting one into the other
        # is doing its job, not inventing anything. Compare on the value.
        if norm := normalise_clock(value):
            return self.identifiers.get(norm)
        return None

    def has_number(self, value: float) -> str | None:
        for known, tool in self.numbers:
            if abs(known - value) <= config.VERIFIER_FLOAT_TOLERANCE:
                return tool
        return None

    def derive(self, value: float) -> tuple[str, str] | None:
        """Whether `value` follows from two evidence numbers by simple arithmetic.

        A price difference, a total, a multiple, a percentage — these are
        things a controller genuinely wants said, and a model will compute
        them whether or not a tool did. "₹5,500 more than the recommended
        option" is 24,000 − 18,500: correct, useful, and not a fabrication.

        Rejecting it is a false positive, and false positives cost as much as
        false negatives — they discard correct answers and teach people to
        ignore the gate. So a derived value is accepted *and labelled with its
        derivation*, which keeps it auditable: a reader can check the
        arithmetic against numbers the tools did return.

        Deliberately narrow: pairs only, no chaining, and both operands must
        themselves be evidence. That keeps the reachable set small enough that
        a fabricated number is very unlikely to land on one by accident.
        """
        if abs(value) < config.VERIFIER_NUMERIC_FLOOR:
            return None

        tol = config.VERIFIER_FLOAT_TOLERANCE
        seen: list[tuple[float, str]] = []
        for number, tool in self.numbers:
            if not any(abs(number - n) <= tol for n, _ in seen):
                seen.append((number, tool))

        for a, tool_a in seen:
            for b, tool_b in seen:
                if a is b:
                    continue
                for expr, result in (
                    (f"{a:g} - {b:g}", a - b),
                    (f"{a:g} + {b:g}", a + b),
                    (f"{a:g} x {b:g}", a * b),
                    (f"{a:g} / {b:g}", a / b if b else None),
                    (f"100 x {a:g} / {b:g}", 100 * a / b if b else None),
                ):
                    if result is None:
                        continue
                    if abs(result - value) <= tol:
                        return expr, f"{tool_a}+{tool_b}"
        return None


def build_evidence(trace: Iterable[TraceEntry]) -> Evidence:
    """Index every scalar every tool returned.

    Arguments are indexed too: an id the model passed *in* came from an earlier
    result or from the controller's own question, so echoing it back is fine.
    """
    evidence = Evidence()

    for entry in trace:
        # `error` counts as evidence: it is text a tool produced, and an id it
        # names ("no fixture covers P-2218") is sourced in exactly the way an
        # id in a successful result is.
        for payload in (entry.result, entry.args, entry.error):
            if payload is None:
                continue
            for scalar in _walk(payload):
                if isinstance(scalar, bool) or scalar is None:
                    continue
                # Decimal is not an int or a float. Postgres returns every
                # numeric column as one, so without this every cost, duty hour
                # and block time read as unsourced.
                if isinstance(scalar, (int, float, Decimal)):
                    evidence.numbers.append((float(scalar), entry.tool))
                    continue
                # Postgres hands back `datetime`, `date` and `time` objects,
                # not strings. Skipping them meant a report time was in the
                # trace, printed in the table, and still not evidence — so
                # every polished answer that mentioned one was rejected and
                # thrown away. Index them as a controller would write them.
                if isinstance(scalar, (dt.datetime, dt.date, dt.time)):
                    scalar = scalar.isoformat()
                if not isinstance(scalar, str):
                    continue

                stamped, rest = times_and_rest(scalar)
                for hhmm in stamped:
                    evidence.identifiers.setdefault(hhmm, entry.tool)

                for pattern in ID_PATTERNS:
                    for match in pattern.findall(scalar if pattern is not CLOCK_RE
                                                 else rest):
                        evidence.identifiers.setdefault(match, entry.tool)
                        # The normalised form too, so one instant is one fact
                        # however either side chooses to spell it.
                        if norm := normalise_clock(match):
                            evidence.identifiers.setdefault(norm, entry.tool)

                # Numbers embedded in prose fields, e.g. a rule's detail string.
                for num in _numbers_in(scalar):
                    evidence.numbers.append((num, entry.tool))

    return evidence


# --------------------------------------------------------------------------
# Extracting claims
# --------------------------------------------------------------------------


def extract_claims(narrative: str) -> list[Claim]:
    """Everything in the prose that has to be backed by evidence."""
    claims: list[Claim] = []
    seen: set[tuple[str, str]] = set()

    stamped, rest = times_and_rest(narrative)
    for pattern in ID_PATTERNS:
        for value in pattern.findall(narrative if pattern is not CLOCK_RE else rest):
            key = ("identifier", value)
            if key not in seen:
                seen.add(key)
                claims.append(Claim("identifier", value))

    for raw in NUMBER_RE.findall(_strip_identifiers(narrative)):
        value = _norm_number(raw)
        if value is None:
            continue
        # Small integers are prose ("all 7 rules", "the 2 options"), not claims
        # about the world. Costs, hours and counts that matter clear the floor.
        if abs(value) < config.VERIFIER_NUMERIC_FLOOR and value.is_integer():
            continue
        key = ("number", raw)
        if key not in seen:
            seen.add(key)
            claims.append(Claim("number", raw))

    return claims


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------


def verify(narrative: str, trace: Iterable[TraceEntry]) -> VerificationResult:
    """Check a drafted answer against the tools that produced it.

    >>> from agent.schemas import TraceEntry
    >>> t = [TraceEntry(tool="lookup", result={"crew_id": "C-1042", "cost": 18500})]
    >>> verify("C-1042 costs 18,500.", t).ok
    True
    >>> verify("C-9999 costs 18,500.", t).ok
    False
    """
    trace = list(trace)
    evidence = build_evidence(trace)
    claims = extract_claims(narrative)

    for claim in claims:
        if claim.kind == "identifier":
            claim.source_tool = evidence.has_identifier(claim.value)
            claim.supported = claim.source_tool is not None
            continue

        value = _norm_number(claim.value)
        if value is None:
            continue

        if source := evidence.has_number(value):
            claim.supported, claim.source_tool = True, source
        elif derived := evidence.derive(value):
            # Not returned by a tool, but it follows from two that were.
            claim.supported = True
            claim.derivation, claim.source_tool = derived

    unsupported = [c for c in claims if not c.supported]

    notes: list[str] = []
    if not trace:
        notes.append("no tools were called — nothing in this answer is sourced")
    for entry in trace:
        if entry.error:
            notes.append(f"tool {entry.tool} errored: {entry.error}")

    return VerificationResult(
        ok=not unsupported and bool(trace),
        claims=claims,
        unsupported=unsupported,
        notes=notes,
        had_trace=bool(trace),
    )


RETRY_INSTRUCTION = """\
Your draft contained claims that no tool output supports: {bad}.

Every identifier and number you state must come from a tool result. Either
call the tool that would establish these, or rewrite the answer without them.
Do not restate them from memory.
"""


def retry_prompt(result: VerificationResult) -> str:
    """What to send back to the model when the gate rejects a draft."""
    return RETRY_INSTRUCTION.format(
        bad=", ".join(c.value for c in result.unsupported) or "(none)"
    )
