"""Guardrails for LLM/agent input and output.

Three controls:
1. Prompt-injection detection — blocks or flags text that tries to override the
   system prompt, exfiltrate secrets, or invoke tools.
2. PII containment — optionally redacts sensitive values before a prompt leaves
   the process boundary.
3. Output validation — enforces size limits and (optionally) JSON shape before
   an answer is trusted or persisted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..governance.pii import kinds as pii_kinds
from ..governance.pii import redact

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "override_instructions",
        re.compile(
            r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|earlier|system)\b.{0,20}\b(instruction|prompt|rules?|message)",
            re.I | re.S,
        ),
    ),
    (
        "reveal_system_prompt",
        re.compile(
            r"\b(reveal|show|print|repeat|expose|leak)\b.{0,30}\b(system prompt|instructions|prompt|rules)\b",
            re.I | re.S,
        ),
    ),
    (
        "role_hijack",
        re.compile(
            r"\b(you are now|act as|pretend to be|new (role|persona)|developer mode|jailbreak|DAN mode)\b",
            re.I,
        ),
    ),
    (
        "secret_exfiltration",
        re.compile(
            r"\b(api[_-]?key|secret|password|token|credential)s?\b.{0,25}\b(print|show|reveal|send|expose|dump)\b",
            re.I | re.S,
        ),
    ),
    (
        "tool_abuse",
        re.compile(
            r"\b(execute|run|eval)\b.{0,20}\b(shell|bash|cmd|powershell|python|os\.system|subprocess)\b",
            re.I | re.S,
        ),
    ),
    (
        "delimiter_escape",
        re.compile(r"(<\|(endoftext|im_start|im_end|system|assistant)\|>|\[/?(INST|SYS)\])", re.I),
    ),
]


@dataclass
class GuardrailReport:
    allowed: bool
    risk: float
    reasons: list[str] = field(default_factory=list)
    pii: set[str] = field(default_factory=set)
    sanitized: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk": round(self.risk, 3),
            "reasons": self.reasons,
            "pii": sorted(self.pii),
        }


def scan_prompt(
    text: str,
    *,
    max_chars: int,
    redact_pii: bool = True,
    block_threshold: float = 1.0,
) -> GuardrailReport:
    text = text or ""
    reasons: list[str] = []
    risk = 0.0

    if len(text) > max_chars:
        reasons.append("prompt_too_large")
        risk += 1.0

    for name, pattern in _INJECTION_PATTERNS:
        hits = len(pattern.findall(text))
        if hits:
            reasons.append(name)
            risk += 0.5 * hits

    pii = pii_kinds(text)
    if pii and not redact_pii:
        reasons.append("pii_present")
        risk += 0.25

    sanitized = redact(text) if redact_pii else text
    return GuardrailReport(
        allowed=risk < block_threshold,
        risk=risk,
        reasons=reasons,
        pii=pii,
        sanitized=sanitized,
        meta={"length": len(text)},
    )


def validate_output(
    text: str,
    *,
    max_chars: int,
    json_mode: bool = False,
    required_keys: list[str] | None = None,
) -> GuardrailReport:
    text = text or ""
    reasons: list[str] = []
    risk = 0.0

    if not text.strip():
        reasons.append("empty_output")
        risk += 1.0
    if len(text) > max_chars:
        reasons.append("output_too_large")
        risk += 1.0

    parsed: Any = None
    if json_mode:
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            reasons.append("invalid_json")
            risk += 1.0
    if parsed is not None and required_keys:
        missing = [key for key in required_keys if key not in parsed]
        if missing:
            reasons.append("missing_keys")
            risk += 0.5

    return GuardrailReport(
        allowed=risk == 0.0,
        risk=risk,
        reasons=reasons,
        sanitized=text,
        meta={"parsed": parsed is not None},
    )
