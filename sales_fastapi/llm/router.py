"""Cost-optimised model router.

Policy:
- Tiny classification / dedupe / JSON extraction -> local nano/small SLM.
- Summaries / translation -> local small SLM, escalating to a cloud flash model.
- Drafting -> local medium, else cloud flash.
- Full pitch / research synthesis -> cloud large model, used sparingly.

Every call passes LLM guardrails, carries a fallback chain ending in the offline
echo provider, and records token + cost usage for budget enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from ..config import settings as default_settings
from ..governance.audit import log_event
from .guardrails import GuardrailReport, scan_prompt, validate_output
from .providers import (
    EchoProvider,
    GeminiProvider,
    GemmaProvider,
    LLMProvider,
    LLMResult,
    OllamaProvider,
    estimate_tokens,
)
from .tasks import TaskSpec, Tier, get_task

# Estimated micro-USD (1e-6 USD) per 1K tokens, input / output.
COST_MICROS_PER_1K: dict[str, tuple[int, int]] = {
    "ollama": (0, 0),
    "echo": (0, 0),
    "gemma-4-27b-it": (100, 400),
    "gemini-2.0-flash": (100, 400),
    "gemini-2.0-flash-lite": (50, 200),
    "gemini-2.5-pro": (1250, 5000),
}


class LLMError(RuntimeError):
    pass


class PromptRejected(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


class AllProvidersFailed(LLMError):
    pass


@dataclass
class RouteResult:
    task: str
    tier: str
    result: LLMResult
    prompt_report: GuardrailReport
    output_report: GuardrailReport
    cost_micros: int
    attempts: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "tier": self.tier,
            "provider": self.result.provider,
            "model": self.result.model,
            "input_tokens": self.result.input_tokens,
            "output_tokens": self.result.output_tokens,
            "latency_ms": self.result.latency_ms,
            "fallback_used": self.result.fallback_used,
            "cost_micros": self.cost_micros,
            "guardrails": {
                "prompt": self.prompt_report.as_dict(),
                "output": self.output_report.as_dict(),
            },
            "attempts": self.attempts,
        }


def estimate_cost_micros(model: str, input_tokens: int, output_tokens: int) -> int:
    input_rate, output_rate = COST_MICROS_PER_1K.get(model, (0, 0))
    if model.startswith("gemma"):
        input_rate, output_rate = COST_MICROS_PER_1K["gemma-4-27b-it"]
    return (input_tokens * input_rate + output_tokens * output_rate) // 1000


class ModelRouter:
    def __init__(
        self,
        providers: dict[str, LLMProvider] | None = None,
        *,
        config: Settings | None = None,
        usage_sink=None,
    ):
        self.settings = config or default_settings
        self.providers = providers or {
            "local": OllamaProvider(),
            "cloud": GeminiProvider(),
            "gemma": GemmaProvider(),
            "echo": EchoProvider(),
        }
        self.usage_sink = usage_sink
        self._month = self._month_key()
        self._tokens_this_month = 0

    # -- budget -----------------------------------------------------------
    def _month_key(self) -> str:
        now = datetime.now(timezone.utc)
        return f"{now.year}-{now.month:02d}"

    def _roll_month(self) -> None:
        current = self._month_key()
        if current != self._month:
            self._month = current
            self._tokens_this_month = 0

    def tokens_used(self) -> int:
        self._roll_month()
        return self._tokens_this_month

    # -- planning ---------------------------------------------------------
    def plan(self, task_name: str) -> list[dict[str, str]]:
        spec = get_task(task_name)
        return [{"provider": key, "model": model} for key, model in self._candidates(spec)]

    def _candidates(self, spec: TaskSpec) -> list[tuple[str, str]]:
        s = self.settings
        local_nano = ("local", s.LLM_LOCAL_NANO_MODEL)
        local_small = ("local", s.LLM_LOCAL_MODEL)
        local_medium = ("local", s.LLM_LOCAL_MEDIUM_MODEL)
        cloud_flash = ("cloud", s.LLM_CLOUD_FLASH_MODEL)
        cloud_large = ("cloud", s.LLM_CLOUD_MODEL)
        gemma = ("gemma", s.LLM_GEMMA_MODEL)
        echo = ("echo", "echo")

        if spec.name == "generate_outreach_message":
            chain = [gemma, local_medium, cloud_flash]
        elif spec.tier == Tier.NANO:
            chain = [local_nano, local_small, cloud_flash]
        elif spec.tier == Tier.SMALL:
            chain = [local_small, cloud_flash, local_medium]
        elif spec.tier == Tier.MEDIUM:
            chain = [local_medium, cloud_flash, local_small]
        else:  # LARGE
            chain = [cloud_large, cloud_flash, local_medium]
        if not spec.allow_external:
            chain = [item for item in chain if item[0] != "cloud"]
        # De-duplicate while preserving order, then guarantee offline fallback.
        seen: set[tuple[str, str]] = set()
        ordered = [item for item in chain if not (item in seen or seen.add(item))]
        ordered.append(echo)
        return ordered

    def _provider(self, key: str) -> LLMProvider | None:
        provider = self.providers.get(key)
        if provider is None or not provider.available:
            return None
        return provider

    # -- execution --------------------------------------------------------
    def run(
        self,
        task_name: str,
        prompt: str,
        *,
        system: str = "",
        user_id: int | None = None,
        db: Session | None = None,
        temperature: float = 0.2,
        redact_pii: bool | None = None,
    ) -> RouteResult:
        self._roll_month()
        spec = get_task(task_name)

        do_redact = (not spec.allow_pii) if redact_pii is None else redact_pii
        prompt_report = scan_prompt(
            prompt,
            max_chars=self.settings.LLM_MAX_INPUT_CHARS,
            redact_pii=do_redact,
        )
        if not prompt_report.allowed:
            self._audit(db, user_id, task_name, "rejected", prompt_report.reasons)
            raise PromptRejected(f"Prompt rejected for task '{task_name}': {prompt_report.reasons}")

        if self.settings.LLM_ENFORCE_BUDGET:
            projected = self.tokens_used() + estimate_tokens(prompt) + spec.max_output_tokens
            if projected > self.settings.LLM_MONTHLY_TOKEN_BUDGET:
                self._audit(db, user_id, task_name, "budget_exceeded", ["monthly_budget"])
                raise BudgetExceeded("Monthly LLM token budget exceeded")

        attempts: list[dict[str, Any]] = []
        fallback_used = False
        for key, model in self._candidates(spec):
            provider = self._provider(key)
            if provider is None:
                attempts.append({"provider": key, "model": model, "status": "unavailable"})
                continue
            try:
                result = provider.generate(
                    prompt=prompt_report.sanitized,
                    system=system,
                    model=model,
                    max_output_tokens=spec.max_output_tokens,
                    temperature=temperature,
                    json_mode=spec.json_mode,
                )
            except Exception as exc:  # provider failure -> next candidate
                attempts.append(
                    {"provider": key, "model": model, "status": f"error:{type(exc).__name__}"}
                )
                fallback_used = True
                continue

            result.fallback_used = fallback_used or attempts_has_failure(attempts)
            output_report = validate_output(
                result.text,
                max_chars=self.settings.LLM_MAX_OUTPUT_CHARS,
                json_mode=spec.json_mode,
            )
            cost = estimate_cost_micros(result.model, result.input_tokens, result.output_tokens)
            self._tokens_this_month += result.input_tokens + result.output_tokens
            attempts.append({"provider": key, "model": model, "status": "ok"})
            self._record(db, user_id, spec, result, cost, result.fallback_used)
            return RouteResult(
                task=task_name,
                tier=spec.tier.value,
                result=result,
                prompt_report=prompt_report,
                output_report=output_report,
                cost_micros=cost,
                attempts=attempts,
            )

        self._audit(db, user_id, task_name, "failed", ["all_providers_failed"])
        raise AllProvidersFailed(f"All providers failed for task '{task_name}'")

    def _record(
        self,
        db: Session | None,
        user_id: int | None,
        spec: TaskSpec,
        result: LLMResult,
        cost: int,
        fallback_used: bool,
    ) -> None:
        if self.usage_sink is not None:
            self.usage_sink(user_id, spec.name, result, cost)
        if db is None:
            return
        from ..models import ModelUsage  # local import avoids cycles

        db.add(
            ModelUsage(
                user_id=user_id or 0,
                task=spec.name,
                tier=spec.tier.value,
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_micros=cost,
                latency_ms=result.latency_ms,
                fallback_used=fallback_used,
            )
        )
        db.commit()

    def _audit(
        self,
        db: Session | None,
        user_id: int | None,
        task: str,
        status: str,
        reasons: list[str],
    ) -> None:
        if db is None:
            return
        log_event(
            db,
            action=f"llm.{task}",
            actor_user_id=user_id,
            resource_type="llm_task",
            resource_id=task,
            status=status,
            detail={"reasons": reasons},
            commit=True,
        )


def attempts_has_failure(attempts: list[dict[str, Any]]) -> bool:
    return any(str(item.get("status", "")).startswith("error") for item in attempts)
