"""Scheduler & business-KPI router.

Endpoints
    POST /api/scheduler/run          – enqueue cron tasks (manual sweep)
    GET  /api/scheduler/status       – scheduler health + queued tasks
    GET  /api/scheduler/tasks        – list registered task definitions
    POST /api/scheduler/clear        – clear queued tasks
    GET  /api/kpi/overview           – headline business KPIs
    GET  /api/kpi/pipeline           – contact pipeline funnel metrics
    GET  /api/kpi/outreach           – outreach / campaign performance
    GET  /api/kpi/costs              – LLM usage & cost summary
    GET  /api/kpi/website            – GA4 website metrics (from GCS snapshot)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..analytics import load_ga4_snapshot
from ..database import get_db
from ..models import (
    Campaign,
    CampaignMessage,
    Contact,
    EmailConnection,
    LinkedInProfile,
    ModelUsage,
    RedditPost,
    User,
    WhatsAppMessage,
)
from ..scheduler import scheduler_service
from ..schemas import SchedulerRunIn
from ..security import decrypt_secret, get_current_user
from ..services import MailSender

router = APIRouter(tags=["scheduler", "kpi"])


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


@router.post("/scheduler/run")
def run_scheduler(
    payload: SchedulerRunIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Enqueue the standard pipeline tasks for this user (manual cron sweep)."""
    task_ids = scheduler_service.enqueue_standard_tasks(user_id=user.id)
    result = {
        "enqueued": len(task_ids),
        "task_ids": task_ids,
        "backend": scheduler_service.backend_status(),
        "notification": {"status": "disabled" if not payload.notify_email else "not_configured"},
    }
    if not payload.notify_email:
        return result

    connection = (
        db.query(EmailConnection)
        .filter(EmailConnection.user_id == user.id)
        .order_by(EmailConnection.is_connected.desc(), EmailConnection.id.asc())
        .first()
    )
    if connection is None or not connection.smtp_host or not connection.email_address:
        return result

    task_lines = "\n".join(f"- {task_id}" for task_id in task_ids)
    body = (
        f"Hi {user.name or 'there'},\n\n"
        f"Your cron sweep has been queued for {user.email}.\n\n"
        f"Tasks queued: {len(task_ids)}\n{task_lines}\n\n"
        f"Queue backend: {scheduler_service.backend_status()}\n"
        "The tasks will be processed by the configured worker."
    )
    try:
        MailSender(
            connection.smtp_host,
            connection.smtp_port,
            connection.email_address,
            decrypt_secret(connection.secret_encrypted),
        ).send(user.email, "Kalisoft cron sweep queued", body, connection.email_address)
        result["notification"] = {"status": "sent", "to": user.email}
    except Exception:  # noqa: BLE001
        result["notification"] = {"status": "failed", "to": user.email}
    return result


@router.get("/scheduler/status")
def scheduler_status(user: User = Depends(get_current_user)):
    """Scheduler health + this user's queued tasks."""
    return scheduler_service.status(user_id=user.id)


@router.get("/scheduler/tasks")
def scheduler_tasks(user: User = Depends(get_current_user)):
    """List the registered recurring task definitions."""
    return {"tasks": scheduler_service.registered_tasks()}


@router.post("/scheduler/clear")
def scheduler_clear(user: User = Depends(get_current_user)):
    """Clear this user's queued tasks."""
    removed = scheduler_service.clear(user_id=user.id)
    return {"cleared": removed}


# ---------------------------------------------------------------------------
# Business KPIs
# ---------------------------------------------------------------------------


@router.get("/kpi/overview")
def kpi_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Headline business KPIs for the authenticated user's workspace."""
    total_contacts = (
        db.query(func.count(Contact.id)).filter(Contact.user_id == user.id).scalar() or 0
    )
    linkedin_signals = (
        db.query(func.count(LinkedInProfile.id)).filter(LinkedInProfile.user_id == user.id).scalar()
        or 0
    )
    reddit_signals = (
        db.query(func.count(RedditPost.id)).filter(RedditPost.user_id == user.id).scalar() or 0
    )
    campaigns = db.query(func.count(Campaign.id)).filter(Campaign.user_id == user.id).scalar() or 0
    messages_sent = (
        db.query(func.count(CampaignMessage.id))
        .filter(CampaignMessage.user_id == user.id, CampaignMessage.status == "sent")
        .scalar()
        or 0
    )
    whatsapp_queued = (
        db.query(func.count(WhatsAppMessage.id))
        .filter(WhatsAppMessage.user_id == user.id, WhatsAppMessage.status == "pending")
        .scalar()
        or 0
    )
    email_connections = (
        db.query(func.count(EmailConnection.id))
        .filter(EmailConnection.user_id == user.id, EmailConnection.is_connected.is_(True))
        .scalar()
        or 0
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contacts_total": total_contacts,
        "signals": {"linkedin": linkedin_signals, "reddit": reddit_signals},
        "campaigns_total": campaigns,
        "messages_sent": messages_sent,
        "whatsapp_pending": whatsapp_queued,
        "email_connections_active": email_connections,
    }


@router.get("/kpi/pipeline")
def kpi_pipeline(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Contact pipeline funnel: intent mix, source mix, recent growth."""
    rows = (
        db.query(Contact.intent, func.count(Contact.id))
        .filter(Contact.user_id == user.id)
        .group_by(Contact.intent)
        .all()
    )
    by_intent = {intent or "unclassified": count for intent, count in rows}

    rows = (
        db.query(Contact.source, func.count(Contact.id))
        .filter(Contact.user_id == user.id)
        .group_by(Contact.source)
        .all()
    )
    by_source = {source or "unknown": count for source, count in rows}

    since = datetime.now(timezone.utc) - timedelta(days=7)
    new_last_7d = (
        db.query(func.count(Contact.id))
        .filter(Contact.user_id == user.id, Contact.created_at >= since)
        .scalar()
        or 0
    )
    return {"by_intent": by_intent, "by_source": by_source, "new_last_7_days": new_last_7d}


@router.get("/kpi/outreach")
def kpi_outreach(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Outreach performance: campaign funnel + per-channel delivery."""
    camp_rows = (
        db.query(Campaign.status, func.count(Campaign.id))
        .filter(Campaign.user_id == user.id)
        .group_by(Campaign.status)
        .all()
    )
    campaigns_by_status = {status: count for status, count in camp_rows}

    msg_rows = (
        db.query(CampaignMessage.status, func.count(CampaignMessage.id))
        .filter(CampaignMessage.user_id == user.id)
        .group_by(CampaignMessage.status)
        .all()
    )
    messages_by_status = {status: count for status, count in msg_rows}

    totals = (
        db.query(
            func.coalesce(func.sum(Campaign.sent_count), 0),
            func.coalesce(func.sum(Campaign.failed_count), 0),
        )
        .filter(Campaign.user_id == user.id)
        .one()
    )
    sent, failed = int(totals[0]), int(totals[1])
    delivery_rate = (sent / (sent + failed)) if (sent + failed) else None
    return {
        "campaigns_by_status": campaigns_by_status,
        "messages_by_status": messages_by_status,
        "sent": sent,
        "failed": failed,
        "delivery_rate": delivery_rate,
    }


@router.get("/kpi/costs")
def kpi_costs(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """LLM usage & cost summary for the workspace."""
    rows = (
        db.query(
            ModelUsage.task,
            func.count(ModelUsage.id),
            func.coalesce(func.sum(ModelUsage.input_tokens), 0),
            func.coalesce(func.sum(ModelUsage.output_tokens), 0),
            func.coalesce(func.sum(ModelUsage.cost_micros), 0),
        )
        .filter(ModelUsage.user_id == user.id)
        .group_by(ModelUsage.task)
        .all()
    )
    by_task = {
        task: {
            "calls": calls,
            "input_tokens": int(in_tok),
            "output_tokens": int(out_tok),
            "cost_micros": int(cost),
        }
        for task, calls, in_tok, out_tok, cost in rows
    }
    total_cost = sum(v["cost_micros"] for v in by_task.values())
    return {
        "by_task": by_task,
        "total_cost_micros": total_cost,
        "total_cost_usd": round(total_cost / 1_000_000, 6),
    }


@router.get("/kpi/website")
def kpi_website(user: User = Depends(get_current_user)):
    """GA4 website metrics parsed from the GCS 'Reports snapshot' export."""
    return load_ga4_snapshot()
