from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from ..config import settings
from ..security import get_current_user
from ..services import GCSStorage

router = APIRouter(tags=["system"])


def _redis_ping() -> str:
    """Redis is disabled for local runs.

    The connection code is intentionally commented out; re-enable it when a
    Redis instance is available.
    """
    # try:
    #     import redis  # type: ignore
    #
    #     client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
    #     client.ping()
    #     return "ok"
    # except Exception as exc:  # noqa: BLE001
    #     return f"unavailable: {exc}"
    return "disabled"


@router.get("/config")
def public_config():
    """Public client config (no secrets)."""
    return {
        "project_name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "google_client_id": settings.GOOGLE_CLIENT_ID if settings.google_signin_configured else "",
        "google_gmail_oauth_configured": settings.google_gmail_oauth_configured,
        "dev_mode": settings.AUTH_DEV_MODE,
    }


@router.get("/health")
def health(request: Request):
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "env": settings.ENV,
        "time": datetime.now(timezone.utc).isoformat(),
        "database": "ok" if request.app.state.db_ready else "degraded",
        "redis": _redis_ping(),
        "gcs_available": GCSStorage().available,
        "google_signin_configured": settings.google_signin_configured,
        "google_gmail_oauth_configured": settings.google_gmail_oauth_configured,
        "dev_mode": settings.AUTH_DEV_MODE,
    }


@router.get("/integrations")
def integrations(user=Depends(get_current_user)):
    return {
        "gcs": {
            "bucket": settings.GCS_BUCKET_CONTACTS,
            "path": settings.GCS_PATH_CONTACTS,
            "available": GCSStorage().available,
        },
        "redis_url": settings.redis_url.split("@")[-1],
        "gemma_model": settings.GEMMA_MODEL,
        "whatsapp": bool(settings.WHATSAPP_API_KEY),
        "linkedin": bool(settings.LINKEDIN_CLIENT_ID),
        "reddit": bool(settings.REDDIT_CLIENT_ID),
        "youtube": bool(settings.YOUTUBE_API_KEY),
        "smtp": bool(settings.SMTP_HOST),
        "imap": bool(settings.IMAP_HOST),
        "scheduler_backend": "redis" if settings.REDIS_URL else "in-memory",
    }


@router.post("/cron/run")
def run_cron(user=Depends(get_current_user)):
    """Trigger the scheduled pipeline tasks.

    In production this is driven by Cloud Scheduler -> Cloud Run Jobs, or a
    Celery beat worker backed by Redis. This endpoint lets the frontend trigger
    a manual sweep.
    """
    # Redis queue is disabled for local runs. Uncomment when Redis is available:
    # import redis  # type: ignore
    #
    # client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
    # for task in tasks:
    #     client.lpush("sales:cron", task)
    # queued = True

    tasks = [
        "sync_gcs_contacts",
        "refresh_email_connections",
        "linkedin_hiring_alerts",
        "reddit_hiring_alerts",
        "whatsapp_reminders",
    ]
    queued = False
    return {"tasks": tasks, "queued_to_redis": queued}
