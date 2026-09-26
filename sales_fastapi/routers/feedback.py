"""Feedback + mail notification + data-security guardrails status.

- ``POST /api/feedback`` stores user feedback and sends a mail notification to
  the workspace owner via the configured Gmail SMTP (never hard-fails: if SMTP
  is not configured the feedback is still stored and ``notified`` stays false).
- ``GET /api/feedback`` lists the current user's feedback.
- ``GET /api/security/status`` reports the active data-security guardrails so
  the UI can surface them (trust signals).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Feedback, User
from ..schemas import FeedbackIn, FeedbackOut
from ..security import get_current_user
from ..services import MailSender

router = APIRouter(tags=["feedback", "security"])


def _notify_feedback(user: User, fb: Feedback) -> bool:
    """Send a mail notification for new feedback. Returns True if sent."""
    if not (settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD):
        return False
    try:
        sender = MailSender(
            smtp_host=settings.SMTP_HOST,
            smtp_port=settings.SMTP_PORT,
            user=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
        )
        body = (
            f"New feedback from {user.name or user.email}\n\n"
            f"Category: {fb.category}\nRating: {fb.rating}/5\nPage: {fb.page or '-'}\n\n"
            f"{fb.message}\n"
        )
        sender.send(
            to=settings.SMTP_USER,
            subject=f"[Kalisoft feedback] {fb.category} ({fb.rating}/5)",
            body=body,
        )
        return True
    except Exception:  # noqa: BLE001 - notification must not break the request
        return False


@router.post("/feedback", status_code=201)
def submit_feedback(
    payload: FeedbackIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fb = Feedback(
        user_id=user.id,
        category=payload.category,
        rating=payload.rating,
        message=payload.message,
        page=payload.page,
    )
    db.add(fb)
    db.commit()
    db.refresh(fb)
    fb.notified = _notify_feedback(user, fb)
    db.commit()
    db.refresh(fb)
    return FeedbackOut.model_validate(fb)


@router.get("/feedback")
def list_feedback(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Feedback)
        .filter(Feedback.user_id == user.id)
        .order_by(Feedback.id.desc())
        .limit(50)
        .all()
    )
    return [FeedbackOut.model_validate(r) for r in rows]


@router.get("/security/status")
def security_status(user: User = Depends(get_current_user)):
    """Data-security guardrails currently enforced (trust signals for the UI)."""
    return {
        "guardrails": [
            {
                "key": "google_signin",
                "label": "Google Sign-In (ADC)",
                "on": settings.google_signin_configured or settings.AUTH_DEV_MODE,
            },
            {"key": "user_scoping", "label": "Per-user data isolation", "on": True},
            {"key": "encryption", "label": "Secrets encrypted at rest (Fernet)", "on": True},
            {
                "key": "pii_redaction",
                "label": "PII redaction in logs/prompts",
                "on": settings.PII_REDACTION_ENABLED,
            },
            {
                "key": "audit_log",
                "label": "Append-only audit trail",
                "on": settings.AUDIT_LOG_ENABLED,
            },
            {
                "key": "rate_limit",
                "label": "Rate limiting (429)",
                "on": settings.RATE_LIMIT_ENABLED,
            },
            {"key": "llm_guardrails", "label": "LLM prompt-injection guardrails", "on": True},
            {
                "key": "retention",
                "label": f"Retention {settings.RETENTION_DAYS_CONTACTS}d contacts / {settings.RETENTION_DAYS_AUDIT}d audit",
                "on": True,
            },
        ],
        "env": settings.ENV,
    }
