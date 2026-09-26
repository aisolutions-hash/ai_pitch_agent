"""Governance and LLM routing endpoints.

These expose classification policy, GCP verification, the audit trail, cost
usage, and the cost-optimised task router. Model execution is authenticated and
audited; the GCP check is status-only and never returns secret values.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..governance.audit import list_events, log_event
from ..governance.classification import policy_summary
from ..governance.gcp_verify import verify_environment
from ..governance.retention import policy as retention_policy
from ..governance.retention import purge
from ..llm.router import (
    AllProvidersFailed,
    BudgetExceeded,
    ModelRouter,
    PromptRejected,
)
from ..llm.tasks import get_task, list_tasks
from ..models import ModelUsage, User
from ..schemas import AuditEventOut, LLMRunIn, LLMRunOut
from ..security import get_current_user

governance_router = APIRouter(prefix="/governance", tags=["governance"])
llm_router = APIRouter(prefix="/llm", tags=["llm"])


@lru_cache
def _router() -> ModelRouter:
    return ModelRouter()


@governance_router.get("/policy")
def governance_policy(user: User = Depends(get_current_user)):
    return {
        "governance_enabled": settings.GOVERNANCE_ENABLED,
        "pii_redaction_enabled": settings.PII_REDACTION_ENABLED,
        "audit_log_enabled": settings.AUDIT_LOG_ENABLED,
        "classification": policy_summary(),
        "retention_days": retention_policy(),
    }


@governance_router.get("/gcp")
def governance_gcp(
    deep: bool = Query(default=False),
    user: User = Depends(get_current_user),
):
    return verify_environment(deep=deep)


@governance_router.get("/audit", response_model=list[AuditEventOut])
def governance_audit(
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return list_events(db, actor_user_id=user.id, limit=limit)


@governance_router.post("/retention/purge")
def governance_purge(
    dry_run: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = purge(db, dry_run=dry_run)
    log_event(
        db,
        action="governance.retention_purge",
        actor_user_id=user.id,
        resource_type="retention",
        status="dry_run" if dry_run else "success",
        detail=result,
        commit=True,
    )
    return result


@governance_router.get("/usage")
def governance_usage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = db.query(ModelUsage).filter(ModelUsage.user_id == user.id)
    total_tokens = (
        db.query(func.coalesce(func.sum(ModelUsage.input_tokens + ModelUsage.output_tokens), 0))
        .filter(ModelUsage.user_id == user.id)
        .scalar()
    )
    total_cost = (
        db.query(func.coalesce(func.sum(ModelUsage.cost_micros), 0))
        .filter(ModelUsage.user_id == user.id)
        .scalar()
    )
    by_provider = (
        base.with_entities(
            ModelUsage.provider,
            func.count(ModelUsage.id),
            func.coalesce(func.sum(ModelUsage.cost_micros), 0),
        )
        .group_by(ModelUsage.provider)
        .all()
    )
    return {
        "calls": base.count(),
        "total_tokens": int(total_tokens or 0),
        "total_cost_micros": int(total_cost or 0),
        "budget_tokens": settings.LLM_MONTHLY_TOKEN_BUDGET,
        "by_provider": [
            {"provider": provider, "calls": calls, "cost_micros": int(cost)}
            for provider, calls, cost in by_provider
        ],
    }


@llm_router.get("/tasks")
def llm_tasks(user: User = Depends(get_current_user)):
    return list_tasks()


@llm_router.get("/plan/{task}")
def llm_plan(task: str, user: User = Depends(get_current_user)):
    try:
        get_task(task)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"task": task, "chain": _router().plan(task)}


@llm_router.post("/run", response_model=LLMRunOut)
def llm_run(
    payload: LLMRunIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        route = _router().run(
            payload.task,
            payload.prompt,
            system=payload.system,
            user_id=user.id,
            db=db,
            temperature=payload.temperature,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PromptRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BudgetExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AllProvidersFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    log_event(
        db,
        action="llm.run",
        actor_user_id=user.id,
        resource_type="llm_task",
        resource_id=payload.task,
        status="success",
        ip_address=request.client.host if request.client else "",
        detail={"cost_micros": route.cost_micros, "provider": route.result.provider},
    )
    db.commit()
    return LLMRunOut(
        task=route.task,
        tier=route.tier,
        provider=route.result.provider,
        model=route.result.model,
        output=route.result.text,
        input_tokens=route.result.input_tokens,
        output_tokens=route.result.output_tokens,
        cost_micros=route.cost_micros,
        fallback_used=route.result.fallback_used,
        guardrails={
            "prompt": route.prompt_report.as_dict(),
            "output": route.output_report.as_dict(),
        },
    )
