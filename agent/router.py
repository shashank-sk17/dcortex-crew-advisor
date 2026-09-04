"""Tier and intent classification.

Deterministic rules run first and settle the overwhelming majority of real
questions. The model is only consulted when the rules abstain, which keeps the
common path free, fast and reproducible — and keeps the classifier auditable,
since every rule-based decision reports which pattern fired.

Tier comes from the intent, never independently: they cannot disagree if only
one of them is ever decided.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from agent import config
from agent.entities import Entities, extract
from agent.llm import LLM
from agent.schemas import Confidence, Intent, Tier

# --------------------------------------------------------------------------
# Rules, most specific first. First match wins.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rule:
    intent: Intent
    pattern: re.Pattern[str]
    name: str
    requires_multi_event: bool = False


def _p(*alts: str) -> re.Pattern[str]:
    return re.compile("|".join(alts), re.I)


RULES: tuple[Rule, ...] = (
    # ---- tier 3 -----------------------------------------------------------
    Rule(
        # These phrasings are explicit enough to stand alone — "both captains
        # are sick" names two events without naming either crew member.
        Intent.JOINT_PLAN,
        _p(r"\bjoint\b", r"\bboth\b.*\bsick\b", r"\bsimultaneous", r"\bacross both\b",
           r"\bboth\b.*\bcall(ed)? in\b"),
        "joint",
    ),
    Rule(
        Intent.SIMULATE_WHATIF,
        _p(r"\bwhat if\b", r"\bsuppose\b", r"\binstead\b", r"\bwould happen\b",
           r"\bif .* were\b"),
        "whatif",
    ),
    Rule(
        Intent.RESOLVE_ILLEGAL,
        _p(r"\blapsed\b", r"\bexpired\b.*\bresolve\b", r"\billegal\b",
           r"\bresolve their\b", r"\bnon-?compliant\b"),
        "resolve_illegal",
    ),
    Rule(
        Intent.RANK_OPTIONS,
        # Note: no bare `\brank\b` — "what is C-2087's rank" is a tier-1
        # lookup about seniority, not a request to rank anything.
        _p(r"\branked\b", r"\brank (the |these )?options\b", r"\brank them\b",
           r"\brecommend", r"\bwhat should\b", r"\bshould (it|we|they|the desk)\b",
           r"\bbest (option|course|plan)\b", r"\bresolution options\b",
           r"\boptions with costs?\b", r"\boptimal\b", r"\bproduce .*options\b",
           r"\brecovery plan\b", r"\boutline .*\bplan\b", r"\bbriefing\b",
           r"\bcheapest\b", r"\bleast (cost|expensive)\b",
           r"\bdraft the\b", r"\bnotification\b"),
        "rank",
    ),
    # ---- tier 2 -----------------------------------------------------------
    Rule(
        Intent.CHECK_LEGALITY,
        _p(r"\bbreach", r"\bis it legal\b", r"\bdoes any rule\b", r"\bany rule\b",
           r"\blegal(ly)? (to |for )?(assign|cover|operate)", r"\bviolat",
           r"\bexceed", r"\bwithin (the )?limits?\b",
           # A bare "Legal?" after a proposed assignment.
           r"\blegal\s*\?", r"\bproposed to (cover|operate|fly)\b", r"\bproposed\b",
           # Prospective duty — a hypothetical, not a stored fact.
           r"\bincluding any planned\b", r"\bif (assigned|rostered)\b",
           # Rest arithmetic (RULE-REST-04) reads like a lookup but is not.
           r"\bearliest .*\breport\b", r"\bmay report\b", r"\bwhen can .*report\b"),
        "legality",
    ),
    Rule(
        Intent.FIND_REPLACEMENT,
        _p(r"\bwho (can|could|should) (cover|fly|operate|replace)\b",
           r"\breplacement\b", r"\bwho do i use\b", r"\bcover(ing)? (for|the)\b",
           r"\bfind (a |someone )?(cover|replacement)\b", r"\bstand ?in\b"),
        "replacement",
    ),
    Rule(
        Intent.IMPACT_OF_EVENT,
        _p(r"\baffected\b", r"\buncrewed\b", r"\buncovered\b", r"\bat risk\b",
           r"\bimmediately\b.*\bflights?\b", r"\bwhich flights\b.*\b(lose|lost)\b",
           r"\bclosed\b", r"\bknock-?on\b"),
        "impact",
    ),
    # ---- tier 1 -----------------------------------------------------------
    Rule(
        Intent.LOOKUP_DUTY_CLOCK,
        _p(r"\bduty hours?\b", r"\bblock hours?\b", r"\bflight hours?\b",
           r"\bheadroom\b", r"\baccrued\b", r"\bduty clock\b", r"\brest\b.*\bhow much\b"),
        "duty_clock",
    ),
    Rule(
        Intent.LOOKUP_RESERVE,
        _p(r"\breserves?\b", r"\bon-?call\b", r"\bstandby\b"),
        "reserve",
    ),
    Rule(
        Intent.LOOKUP_CERT,
        _p(r"\bcertificat", r"\bexpir", r"\bmedical\b", r"\blicence\b", r"\blicense\b",
           r"\brecurrent\b", r"\bdangerous goods\b", r"\bvalid(ity)?\b"),
        "cert",
    ),
    Rule(
        Intent.EXPLAIN_RULE,
        _p(r"\bwhat (is|does)\b.*\brule\b", r"\bexplain\b.*\brule\b",
           r"\bwhich rule\b", r"\brule\b.*\bmean\b"),
        "explain_rule",
    ),
    Rule(
        # Risk scores are provided input, not something we model — but a
        # question about one is still a lookup, and must not fall through.
        Intent.LOOKUP_CREW,
        _p(r"\brisk score\b", r"\bdisruption[- ]risk\b", r"\brisk signal",
           r"\bwhat drives\b"),
        "risk",
    ),
    Rule(
        Intent.LOOKUP_FLIGHT,
        _p(r"\bwhich flights?\b", r"\bflights? (depart|arrive|from|to)\b",
           r"\bdepartures?\b", r"\barrivals?\b", r"\bschedule\b",
           # Network shape is a question about the flight table.
           r"\bstations?\b.*\b(serve|network|nonstop|non-stop)\b",
           r"\bnetwork\b", r"\bnonstop\b", r"\bnon-stop\b", r"\broutes?\b"),
        "flight",
    ),
    Rule(
        Intent.LOOKUP_ROSTER,
        _p(r"\brostered?\b", r"\bpairing\b", r"\bwho is (flying|operating|on)\b",
           r"\bcrew (complement|list|of)\b"),
        "roster",
    ),
    Rule(
        Intent.LOOKUP_CREW,
        _p(r"\bwho\b", r"\blist all\b", r"\bhow many\b", r"\bqualified\b",
           r"\brating\b", r"\bbased at\b"),
        "crew",
    ),
)


@dataclass(slots=True)
class Route:
    """The router's decision, with its reasoning attached."""

    intent: Intent
    tier: Tier
    entities: Entities
    confidence: Confidence = Confidence.HIGH
    matched_rule: str | None = None
    used_llm: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "intent": str(self.intent),
            "tier": int(self.tier),
            "entities": self.entities.to_dict(),
            "confidence": str(self.confidence),
            "matched_rule": self.matched_rule,
            "used_llm": self.used_llm,
            "notes": self.notes,
        }


def _is_multi_event(text: str, ents: Entities) -> bool:
    """Two disruptions at once — the S6 shape.

    Two crew ids alone is not enough ("can C-1042 cover for C-2087?" names two
    and is a single event), so require a disruption verb as well.
    """
    disruption = re.search(
        r"\bsick\b|\bcalls?(ed)? in\b|\bout\b|\bunavailable\b", text, re.I
    )
    if not disruption:
        return False

    named_twice = (
        len(ents.crew_ids) >= 2
        or len(ents.pairing_ids) >= 2
        or len(ents.aircraft) >= 2
    )
    # "both captains are sick" is two events without naming either one.
    said_twice = re.search(r"\bboth\b|\bsimultaneous|\btwo\b.*\bcaptains?\b", text, re.I)
    return named_twice or bool(said_twice)


def route_deterministic(text: str, ents: Entities | None = None) -> Route | None:
    """Classify by pattern. Returns None when no rule is confident enough."""
    ents = ents if ents is not None else extract(text)
    multi = _is_multi_event(text, ents)

    for rule in RULES:
        if rule.requires_multi_event and not multi:
            continue
        if not rule.pattern.search(text):
            continue

        intent = rule.intent
        notes: list[str] = []

        # A ranking ask over two concurrent disruptions is a joint plan, even
        # when the word "joint" never appears.
        if intent is Intent.RANK_OPTIONS and multi:
            intent = Intent.JOINT_PLAN
            notes.append("upgraded to JOINT_PLAN: two concurrent events")

        return Route(
            intent=intent,
            tier=intent.tier,
            entities=ents,
            confidence=Confidence.HIGH,
            matched_rule=rule.name,
            notes=notes,
        )
    return None


ROUTER_INSTRUCTIONS = """\
You classify crew-control questions. Reply with JSON only:
{"intent": "<INTENT>", "confidence": "high|medium|low"}

Valid intents:
  Tier 1  LOOKUP_ROSTER LOOKUP_RESERVE LOOKUP_DUTY_CLOCK LOOKUP_CERT
          LOOKUP_FLIGHT LOOKUP_CREW EXPLAIN_RULE
  Tier 2  FIND_REPLACEMENT CHECK_LEGALITY IMPACT_OF_EVENT
  Tier 3  RANK_OPTIONS SIMULATE_WHATIF JOINT_PLAN RESOLVE_ILLEGAL

Entities are already extracted deterministically; classify the *kind* of ask.
"""


def route_llm(text: str, ents: Entities, llm: LLM) -> Route:
    """Fallback path. Only reached when every deterministic rule abstained."""
    from agent.exemplars import exemplar_block

    system = ROUTER_INSTRUCTIONS
    if block := exemplar_block():
        system += f"\nWorked examples (identifiers masked):\n{block}\n"

    response = llm.complete(
        system=system,
        messages=[{"role": "user", "content": text}],
        model=config.ROUTER_MODEL,
        max_tokens=64,
    )

    try:
        payload = json.loads(response.text)
        intent = Intent(payload["intent"])
        confidence = Confidence(payload.get("confidence", "medium"))
    except (json.JSONDecodeError, KeyError, ValueError):
        # Unparseable, or a placeholder client. Degrade to the safest guess:
        # a lookup, which reads data and changes nothing.
        return Route(
            intent=Intent.LOOKUP_CREW,
            tier=Tier.LOOKUP,
            entities=ents,
            confidence=Confidence.LOW,
            used_llm=True,
            notes=["router LLM gave no usable classification; defaulted to lookup"],
        )

    return Route(
        intent=intent,
        tier=intent.tier,
        entities=ents,
        confidence=confidence,
        used_llm=True,
    )


def route(text: str, llm: LLM | None = None) -> Route:
    """Classify a controller's question.

    >>> r = route("Who is on reserve at BLR on 2026-09-15?")
    >>> r.intent, r.tier
    (<Intent.LOOKUP_RESERVE: 'LOOKUP_RESERVE'>, <Tier.LOOKUP: 1>)

    >>> route("Both A320 captains are sick. Give the optimal joint plan.").tier
    <Tier.CONSEQUENCE: 3>
    """
    ents = extract(text)
    if decided := route_deterministic(text, ents):
        return decided

    if llm is None:
        from agent.llm import default_llm

        llm = default_llm()
    return route_llm(text, ents, llm)
