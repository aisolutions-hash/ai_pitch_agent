"""PII detection and redaction.

Governance rule: personally identifiable data must be masked before it is
logged, sent to an LLM, or exported. Detection is regex-based (deterministic,
offline, no external calls) and errs on the side of masking.

India-aware patterns are included (Aadhaar, PAN, GSTIN) alongside generic ones
(email, phone, card, IP). This module has no project dependencies so it can be
used by both the governance and llm layers without import cycles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Ordered so more specific patterns win before broad numeric ones.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    (
        "GSTIN",
        re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9][Z][A-Z0-9]\b"),
    ),
    ("AADHAAR", re.compile(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b")),
    ("CARD", re.compile(r"\b(?:\d[ \-]?){13,19}\b")),
    ("PHONE", re.compile(r"\b(?:\+?91[\-\s]?)?[6-9]\d{9}\b")),
    ("PHONE", re.compile(r"\b\+?\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}\b")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]

_LABEL = {
    "EMAIL": "EMAIL",
    "PAN": "PAN",
    "GSTIN": "GSTIN",
    "AADHAAR": "AADHAAR",
    "CARD": "CARD",
    "PHONE": "PHONE",
    "IP": "IP",
}


def _luhn(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)]
    if len(digits) < 13:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


@dataclass(frozen=True)
class Detection:
    kind: str
    value: str
    start: int
    end: int


def detect(text: str) -> list[Detection]:
    """Return every PII match in ``text`` (possibly overlapping kinds)."""
    if not text:
        return []
    found: list[Detection] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            # Cards are numeric and overlap with Aadhaar/phone; require Luhn.
            if kind == "CARD" and not _luhn(value):
                continue
            found.append(Detection(kind, value, match.start(), match.end()))
    found.sort(key=lambda d: d.start)
    return found


def kinds(text: str) -> set[str]:
    return {d.kind for d in detect(text)}


def redact(text: str, *, keep: int = 0) -> str:
    """Replace PII with ``[KIND]`` tokens, from right to left to keep offsets."""
    if not text:
        return ""
    detections = detect(text)
    if not detections:
        return text
    out = text
    for detection in reversed(detections):
        token = f"[{_LABEL.get(detection.kind, 'PII')}]"
        if keep > 0 and len(detection.value) > keep:
            token = detection.value[:keep] + token
        out = out[: detection.start] + token + out[detection.end :]
    return out


def mask(text: str) -> str:
    """Softer masking that preserves shape for human-readable logs."""
    if not text:
        return ""

    def _mask_email(match: re.Match[str]) -> str:
        local, _, domain = match.group(0).partition("@")
        return f"{local[:1]}***@{domain}"

    def _mask_digits(match: re.Match[str]) -> str:
        digits = match.group(0)
        visible = digits[-4:] if len(digits) >= 4 else digits
        return "*" * max(len(digits) - len(visible), 0) + visible

    out = _PATTERNS[0][1].sub(_mask_email, text)
    for kind, pattern in _PATTERNS[1:]:
        out = pattern.sub(
            lambda m, k=kind: (
                _mask_digits(m)
                if k in {"PHONE", "AADHAAR", "CARD"}
                else f"[{_LABEL.get(k, 'PII')}]"
            ),
            out,
        )
    return out


def redact_structured(data: Any, *, depth: int = 0) -> Any:
    """Recursively redact PII in dicts / lists / scalars used for logging."""
    if depth > 12:
        return data
    if isinstance(data, str):
        return redact(data)
    if isinstance(data, dict):
        return {str(key): redact_structured(value, depth=depth + 1) for key, value in data.items()}
    if isinstance(data, (list, tuple, set)):
        return [redact_structured(item, depth=depth + 1) for item in data]
    return data
