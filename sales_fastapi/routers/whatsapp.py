"""WhatsApp/WeChat channel via the Wechaty gateway.

Outbound sends are authenticated + audited and persisted to `whatsapp_messages`.
The inbound webhook is unauthenticated (server-to-server) but protected by an
HMAC-SHA256 signature when `WECHATY_WEBHOOK_SECRET` is configured.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..governance.audit import log_event
from ..models import Contact, User, WhatsAppMessage
from ..schemas import (
    WhatsAppInbound,
    WhatsAppMessageOut,
    WhatsAppSendRequest,
    WhatsAppSendResponse,
)
from ..security import get_current_user
from ..services import infer_intent
from ..wechaty import WechatyGateway, verify_webhook_signature

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.get("/status")
def whatsapp_status(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    gateway = WechatyGateway()
    return {
        "enabled": settings.WHATSAPP_ENABLED,
        "gateway_url": gateway.base_url,
        "queued": db.query(WhatsAppMessage).filter(WhatsAppMessage.user_id == user.id).count(),
        "gateway": gateway.health(),
    }


@router.get("/messages", response_model=list[WhatsAppMessageOut])
def list_messages(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(WhatsAppMessage)
        .filter(WhatsAppMessage.user_id == user.id)
        .order_by(WhatsAppMessage.created_at.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )


@router.post("/send", response_model=WhatsAppSendResponse)
def send_message(
    payload: WhatsAppSendRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not settings.WHATSAPP_ENABLED:
        raise HTTPException(status_code=503, detail="WhatsApp channel is disabled")

    gateway = WechatyGateway()
    try:
        result = gateway.send_text(payload.to, payload.text)
    except Exception as exc:  # noqa: BLE001 - surfaced as 502
        raise HTTPException(status_code=502, detail=f"Wechaty gateway error: {exc}") from exc

    record = WhatsAppMessage(
        user_id=user.id,
        phone_number=payload.to,
        message=payload.text,
        status="sent",
        sent_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    log_event(
        db,
        action="whatsapp.send",
        actor_user_id=user.id,
        resource_type="whatsapp",
        resource_id=str(record.id),
        ip_address=request.client.host if request.client else "",
        detail={"to": payload.to, "gateway_id": result.get("id", "")},
        commit=True,
    )
    return WhatsAppSendResponse(
        ok=True,
        id=str(result.get("id", record.id)),
        to=payload.to,
        status=result.get("status", "sent"),
        provider=result.get("provider", ""),
    )


@router.post("/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    signature = request.headers.get("x-wechaty-signature", "")
    if not verify_webhook_signature(raw, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        inbound = WhatsAppInbound.model_validate_json(raw or b"{}")
    except Exception as exc:  # noqa: BLE001 - malformed payload
        raise HTTPException(status_code=400, detail=f"Invalid webhook payload: {exc}") from exc

    intent = infer_intent(inbound.text)
    matched_user_id = 0
    if inbound.from_id:
        contact = db.query(Contact).filter(Contact.phone == inbound.from_id).first()
        if contact is not None:
            matched_user_id = contact.user_id

    record = WhatsAppMessage(
        user_id=matched_user_id,
        phone_number=inbound.from_id,
        message=inbound.text,
        status="received",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    log_event(
        db,
        action="whatsapp.inbound",
        actor_user_id=matched_user_id,
        resource_type="whatsapp",
        resource_id=str(record.id),
        detail={"from": inbound.from_id, "intent": intent},
        commit=True,
    )
    return {
        "ok": True,
        "message_id": record.id,
        "matched_user_id": matched_user_id,
        "intent": intent,
    }
