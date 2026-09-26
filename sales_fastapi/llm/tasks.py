"""LLM task registry.

Each task declares a model tier, an output-token ceiling, and whether raw PII
may be sent to an external provider. The router uses this to pick the cheapest
model that can do the job (small local models for classification/JSON work,
larger/cloud models only for genuine reasoning).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    NANO = "nano"  # deterministic / tiny local model
    SMALL = "small"  # local SLM (e.g. 0.5B-3B)
    MEDIUM = "medium"  # local 7B-8B or cheap cloud flash model
    LARGE = "large"  # cloud reasoning model, used sparingly


@dataclass(frozen=True)
class TaskSpec:
    name: str
    tier: Tier
    description: str
    max_output_tokens: int = 512
    json_mode: bool = False
    allow_external: bool = True
    allow_pii: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)


TASKS: dict[str, TaskSpec] = {
    "classify_intent": TaskSpec(
        name="classify_intent",
        tier=Tier.SMALL,
        description="Map a message/context to a sales intent label",
        max_output_tokens=32,
        json_mode=True,
        allow_external=False,
    ),
    "extract_entities": TaskSpec(
        name="extract_entities",
        tier=Tier.SMALL,
        description="Pull company / person / role entities from text",
        max_output_tokens=256,
        json_mode=True,
    ),
    "summarize_profile": TaskSpec(
        name="summarize_profile",
        tier=Tier.SMALL,
        description="Condense a LinkedIn/company profile",
        max_output_tokens=256,
    ),
    "dedupe_match": TaskSpec(
        name="dedupe_match",
        tier=Tier.NANO,
        description="Decide whether two contact records are the same entity",
        max_output_tokens=16,
        json_mode=True,
        allow_external=False,
    ),
    "draft_outreach_email": TaskSpec(
        name="draft_outreach_email",
        tier=Tier.MEDIUM,
        description="Draft a short outreach email",
        max_output_tokens=700,
    ),
    "translate_script": TaskSpec(
        name="translate_script",
        tier=Tier.SMALL,
        description="Translate a voice script to an Indian language",
        max_output_tokens=512,
    ),
    "generate_pitch": TaskSpec(
        name="generate_pitch",
        tier=Tier.LARGE,
        description="Full multi-section pitch generation",
        max_output_tokens=2000,
    ),
    "research_synthesis": TaskSpec(
        name="research_synthesis",
        tier=Tier.LARGE,
        description="Synthesize multi-source research into findings",
        max_output_tokens=1500,
    ),
    "generate_outreach_message": TaskSpec(
        name="generate_outreach_message",
        tier=Tier.SMALL,
        description="Personalise an outreach message for one contact",
        max_output_tokens=800,
        allow_external=True,
        allow_pii=True,
        tags=("outreach", "gemma"),
    ),
}


def get_task(name: str) -> TaskSpec:
    try:
        return TASKS[name]
    except KeyError as exc:
        raise KeyError(f"Unknown LLM task '{name}'") from exc


def list_tasks() -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "tier": spec.tier.value,
            "description": spec.description,
            "json_mode": spec.json_mode,
            "allow_external": spec.allow_external,
            "allow_pii": spec.allow_pii,
        }
        for spec in TASKS.values()
    ]
