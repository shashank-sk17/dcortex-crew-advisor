"""PII/sensitive-data redaction layer for the REST API boundary.

Per the team's data-handling note: PII must be redacted in the initial/outer
layer, not deep in business logic. The current vendored dataset (crew.json
etc.) has NONE of these fields today -- see docs/DATA_STORAGE_DESIGN.md §5 --
so this module is defense-in-depth for when such fields get added, not a fix
for an existing leak. It's applied at serialization time so it can never be
forgotten on a newly added field.

Categories covered, modeled on India's DPDP Act 2023 / the earlier SPDI
Rules 2011 definition of sensitive personal data (financial info, health
records, government IDs, biometric info):
  - email, phone                    -- regex, reliable
  - Aadhaar, PAN, passport number   -- regex, format-specific (India context)
  - payment card numbers            -- regex + Luhn check, to avoid
                                        false-positiving on arbitrary long
                                        digit sequences
  - physical/home address           -- field-name/type only, NEVER generic
                                        free-text pattern matching (address
                                        text looks like ordinary prose --
                                        that has terrible precision)
  - date of birth, health/medical
    notes, bank details, government
    ID numbers generally, emergency
    contact info                    -- field-name only, same reasoning as
                                        address: no reliable content pattern
                                        distinguishes a DOB from any other
                                        date, or a diagnosis from any other
                                        sentence.

Deliberately NOT redacted: crew name, rank, base, crew_id. These are
operationally necessary for the product to function (a controller must know
who to call) -- PII handling here means stripping data that has no
operational purpose in these responses, not hiding identity itself. This API
has no auth/access-control layer (out of scope per the problem statement),
so "redact what's dangerous, keep what's needed to do the job" is the
working principle, not "redact everything personal."
"""
from __future__ import annotations

import re
import typing
from typing import Any

from pydantic import BaseModel, model_serializer

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# +91 98765 43210 / (080) 1234-5678 style (leading + or parens), or a bare
# 7-15 digit run. Deliberately does NOT match hyphenated digit groups without
# a leading +/parens -- indistinguishable from an ISO date (2026-09-15) or a
# flight/pairing ID suffix in this domain. Order matters: this must run
# AFTER the more specific patterns below, or it would swallow them under the
# generic PHONE label instead of their correct one.
_PHONE_RE = re.compile(r"(?<!\d)(?:\+\d[\d\s\-().]{6,14}\d|\d{7,15})(?!\d)")

# Aadhaar: 12 digits, conventionally displayed in 3 groups of 4 (with space
# or hyphen). An ungrouped bare 12-digit Aadhaar still gets caught by the
# generic phone pattern above (labeled PHONE instead of AADHAAR) -- accepted
# tradeoff, since requiring the grouped display format keeps this pattern
# from misfiring on other 12-digit sequences.
#
# The lookbehind/lookahead guard against a 4th adjacent group of 4 digits is
# required: without it, a 16-digit card-shaped number that FAILS its Luhn
# check (so _redact_cards leaves it alone) would have its first 3 groups
# mis-matched as an Aadhaar number -- found via testing, not hypothetical.
_AADHAAR_RE = re.compile(r"(?<!\d{4}[\s-])(?<!\d)\d{4}[\s-]\d{4}[\s-]\d{4}(?!\d)(?![\s-]\d{4})")

# PAN: 5 letters, 4 digits, 1 letter -- e.g. ABCDE1234F. Very specific shape,
# negligible false-positive risk against anything else in this domain.
_PAN_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Z0-9])")

# Indian passport: 1 letter + 7 digits, no separator -- e.g. A1234567.
# Doesn't collide with crew_id (C-1042, hyphenated), aircraft tails (VT-DXA,
# no digits), or flight numbers (DX401, 3 digits not 7).
_PASSPORT_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]\d{7}(?![A-Za-z0-9])")

_IPV4_RE = re.compile(r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)")

# Candidate payment-card sequences (13-19 digits, optionally grouped by
# spaces/hyphens) -- verified with a Luhn checksum before redacting, so an
# arbitrary long numeric ID doesn't get mislabeled as a card number.
_CARD_CANDIDATE_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){13,19}(?!\d)")

# Field names that are unconditionally redacted regardless of content --
# these categories (address, DOB, health, financial, other government IDs)
# have no generic content pattern that reliably distinguishes them from
# ordinary text or from other operational dates/numbers in this domain.
_SENSITIVE_FIELD_NAMES = {
    "address", "physical_address", "home_address", "residential_address",
    "date_of_birth", "dob", "birth_date",
    "medical_notes", "medical_condition", "health_notes", "diagnosis",
    "bank_account", "bank_account_number", "ifsc_code", "iban",
    "national_id", "ssn", "tax_id", "government_id",
    "emergency_contact", "next_of_kin", "emergency_contact_number",
    "photo", "biometric_id", "signature",
}


def _luhn_valid(digits: str) -> bool:
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _redact_cards(text: str) -> str:
    def repl(m: re.Match) -> str:
        digits = re.sub(r"[ \-]", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return "[REDACTED_CARD]"
        return m.group(0)

    return _CARD_CANDIDATE_RE.sub(repl, text)


def redact_pii_text(value: str) -> str:
    """Applies every content-pattern redaction, most specific first (so a
    PAN or passport number gets its correct label instead of being swallowed
    by the generic phone pattern). Never call this on structured IDs
    (crew_id, flight_id, etc.) -- it's for free-text/narrative fields only."""
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = _redact_cards(value)
    value = _PAN_RE.sub("[REDACTED_PAN]", value)
    value = _PASSPORT_RE.sub("[REDACTED_PASSPORT]", value)
    value = _AADHAAR_RE.sub("[REDACTED_AADHAAR]", value)
    value = _IPV4_RE.sub("[REDACTED_IP]", value)
    value = _PHONE_RE.sub("[REDACTED_PHONE]", value)
    return value


class Address(str):
    """Marker type for a field that holds a physical address (or any other
    field-name-based sensitive category listed in _SENSITIVE_FIELD_NAMES).
    Always fully redacted on serialization regardless of content -- address/
    DOB/health/financial text isn't reliably pattern-matchable the way an
    email or PAN number is, so any field of this type (or with a matching
    name) is masked unconditionally rather than content-scanned.

    Implements __get_pydantic_core_schema__ so Pydantic v2 treats it exactly
    like `str` for validation -- a bare `str` subclass otherwise raises
    PydanticSchemaGenerationError the moment it's used as a field type
    (found via testing: a model with a field typed `Address` failed at
    class-definition time, not just at redaction time).
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any):
        from pydantic_core import core_schema

        return core_schema.no_info_after_validator_function(cls, core_schema.str_schema())


class PIISafeModel(BaseModel):
    """Base for every API response model. Serializes with PII/sensitive
    fields redacted automatically -- both at the top level AND inside nested
    objects/lists, so a sensitive field buried in a nested structure can't
    slip through just because it isn't a direct field of the outer model.
    """

    @model_serializer(mode="wrap")
    def _redact_on_dump(self, handler: Any) -> dict:
        dumped = handler(self)
        annotations = {name: f.annotation for name, f in type(self).model_fields.items()}
        return _redact_value(dumped, annotations)


def _annotation_marks_address(annotation: Any) -> bool:
    """True if `annotation` is `Address` itself, OR wraps it -- e.g.
    `Address | None`, `Optional[Address]`, `list[Address]`. A plain identity
    check (`annotation is Address`) misses all of these: found via testing
    that `Optional[Address]` and `list[Address]` fields leaked completely
    unredacted, because typing wraps `Address` inside a Union/generic-alias
    object that is never `is Address` itself."""
    if annotation is Address:
        return True
    return any(_annotation_marks_address(a) for a in typing.get_args(annotation))


def _is_sensitive_field(field_name: str, annotation: Any = None) -> bool:
    return _annotation_marks_address(annotation) or field_name.lower() in _SENSITIVE_FIELD_NAMES


def _redact_value(value: Any, field_annotations: dict[str, Any] | None = None) -> Any:
    """Recursively redacts a value. `field_annotations` (name -> type) is
    only meaningful for the dict literally corresponding to a Pydantic
    model's own fields (passed in from _redact_on_dump); nested dicts get
    re-checked purely by field name, since we don't have their model class
    at that point -- this is the fix for the gap where nested objects
    weren't field-name-checked at all before.

    When a field is sensitive AND its value is a list (e.g. `list[Address]`),
    every string item in that list is fully redacted too, not just a dict
    value directly under that key -- otherwise `list[Address]`/`Optional[
    Address]` fields would leak (also found via testing)."""
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            annotation = (field_annotations or {}).get(k)
            if _is_sensitive_field(k, annotation):
                result[k] = _redact_sensitive_leaf(v)
            else:
                result[k] = _redact_value(v)
        return result
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, str):
        return redact_pii_text(value)
    return value


def _redact_sensitive_leaf(value: Any) -> Any:
    """Applies unconditional full redaction to a value already identified as
    a sensitive field -- a bare string, or every string inside a list."""
    if isinstance(value, str):
        return "[REDACTED_ADDRESS]"
    if isinstance(value, list):
        return [_redact_sensitive_leaf(v) for v in value]
    return value
