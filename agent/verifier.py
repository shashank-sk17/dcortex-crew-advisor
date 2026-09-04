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

import re
from dataclasses import dataclass, field
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

ID_PATTERNS = (CREW_RE, PAIRING_RE, FLIGHT_ID_RE, FLIGHT_NO_RE, RULE_RE, AIRCRAFT_RE)


@dataclass(slots=True)
class Claim:
    """One checkable assertion lifted out of the narrative."""

    kind: str          # "identifier" | "number"
    value: str
    supported: bool = False
    source_tool: str | None = None


@dataclass(slots=True)
class VerificationResult:
    ok: bool
    claims: list[Claim] = field(default_factory=list)
    unsupported: list[Claim] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return f"verified: {len(self.claims)} claims all traced to tool output"
        bad = ", ".join(c.value for c in self.unsupported)
        return f"UNVERIFIED: {len(self.unsupported)} untraced claim(s): {bad}"


# --------------------------------------------------------------------------
# Building the evidence set
# --------------------------------------------------------------------------


def _walk(node: Any) -> Iterable[Any]:
    """Yield every scalar in an arbitrarily nested tool result."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk(value)
    elif isinstance(node, (list, tuple, set)):
        for item in node:
            yield from _walk(item)
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
        return self.identifiers.get(value)

    def has_number(self, value: float) -> str | None:
        for known, tool in self.numbers:
            if abs(known - value) <= config.VERIFIER_FLOAT_TOLERANCE:
                return tool
        return None


def build_evidence(trace: Iterable[TraceEntry]) -> Evidence:
    """Index every scalar every tool returned.

    Arguments are indexed too: an id the model passed *in* came from an earlier
    result or from the controller's own question, so echoing it back is fine.
    """
    evidence = Evidence()

    for entry in trace:
        for payload in (entry.result, entry.args):
            if payload is None:
                continue
            for scalar in _walk(payload):
                if isinstance(scalar, bool) or scalar is None:
                    continue
                if isinstance(scalar, (int, float)):
                    evidence.numbers.append((float(scalar), entry.tool))
                    continue
                if not isinstance(scalar, str):
                    continue

                for pattern in ID_PATTERNS:
                    for match in pattern.findall(scalar):
                        evidence.identifiers.setdefault(match, entry.tool)

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

    for pattern in ID_PATTERNS:
        for value in pattern.findall(narrative):
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
            source = evidence.has_identifier(claim.value)
        else:
            value = _norm_number(claim.value)
            source = evidence.has_number(value) if value is not None else None

        claim.supported = source is not None
        claim.source_tool = source

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
