"""Bulk outreach campaigns with human-in-the-loop review.

Flow: create (render + optional Gemma personalisation) -> pending_review ->
approve / edit -> send (email / WhatsApp / WeChat) -> status updates.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..governance.audit import log_event
from ..llm.router import ModelRouter
from ..models import (
    Campaign,
    CampaignMessage,
    Contact,
    EmailConnection,
    MessageTemplate,
    User,
)
from ..schemas import (
    CampaignCreate,
    CampaignDetail,
    CampaignMessageOut,
    CampaignMessageUpdate,
    CampaignOut,
    CampaignSendResult,
)
from ..security import get_current_user
from ..services import MailSender
from ..templating import contact_context, render
from ..wechaty import WechatyGateway

router = APIRouter(prefix="/campaigns", tags=["campaigns"])

SENDER_CONTEXT = {
    "sender_name": "Kalisoft AI",
    "sender_email": "ai.solutions@kalisoftai.in",
    "product": "Kalisoft AI Sales Automation",
    "calendar_link": "https://kalisoftai.in/demo",
}


@lru_cache
def _llm_router() -> ModelRouter:
    return ModelRouter()


def _ai_personalise(template: MessageTemplate, contact: Contact, channel: str) -> tuple[str, str]:
    """Return (model_name, body). Falls back to the template render on any failure."""
    base_body = render(template.body, {**SENDER_CONTEXT, **contact_context(contact)})
    if not settings.LLM_ENABLED:
        return ("template", base_body)
    prompt = (
        f"Write a concise {channel} outreach message for a B2B sales campaign.\n"
        f"Strategy: {template.strategy}. Funnel stage: {template.funnel_stage}.\n"
        f"Recipient: {contact.name or 'decision maker'} at {contact.company or 'the company'}.\n"
        f"Intent: {contact.intent or 'general'}. Context: {contact.context or ''}.\n"
        f"Product: {SENDER_CONTEXT['product']}. Sender: {SENDER_CONTEXT['sender_name']}.\n\n"
        f"Base draft to personalise (keep under 120 words):\n{base_body}\n\n"
        "Return only the final message body."
    )
    try:
        route = _llm_router().run(
            "generate_outreach_message", prompt, system="You are a precise B2B sales copywriter."
        )
        text = route.result.text.strip()
        if route.result.provider == "echo" or not text:
            return ("template", base_body)
        return (route.result.model, text)
    except Exception:  # noqa: BLE001 - fall back to the template
        return ("template", base_body)


@router.post("", response_model=CampaignDetail, status_code=201)
def create_campaign(
    payload: CampaignCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    template = (
        db.query(MessageTemplate)
        .filter(
            MessageTemplate.id == payload.template_id, MessageTemplate.user_id.in_([user.id, 0])
        )
        .first()
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    query = db.query(Contact).filter(Contact.user_id == user.id)
    if payload.filter.intent:
        query = query.filter(Contact.intent == payload.filter.intent)
    if payload.filter.source:
        query = query.filter(Contact.source == payload.filter.source)
    if payload.filter.q:
        like = f"%{payload.filter.q}%"
        query = query.filter(
            Contact.company.ilike(like) | Contact.name.ilike(like) | Contact.email.ilike(like)
        )
    contacts = query.order_by(Contact.created_at.desc()).limit(payload.filter.limit).all()
    if not contacts:
        raise HTTPException(status_code=400, detail="No contacts matched the campaign filter")

    campaign = Campaign(
        user_id=user.id,
        name=payload.name,
        channel=payload.channel,
        strategy=payload.strategy,
        template_id=template.id,
        status="pending_review",
        total=len(contacts),
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    model_used = "template"
    for contact in contacts:
        subject = render(template.subject, {**SENDER_CONTEXT, **contact_context(contact)})
        model_name, body = _ai_personalise(template, contact, payload.channel)
        if model_name != "template":
            model_used = model_name
        db.add(
            CampaignMessage(
                campaign_id=campaign.id,
                user_id=user.id,
                contact_id=contact.id,
                to_address=contact.phone
                if payload.channel in {"whatsapp", "wechat"}
                else contact.email,
                rendered_subject=subject,
                rendered_body=body,
                status="pending_review",
            )
        )
    campaign.ai_model = model_used if payload.use_ai else "template"
    db.commit()
    db.refresh(campaign)

    log_event(
        db,
        action="campaign.create",
        actor_user_id=user.id,
        resource_type="campaign",
        resource_id=str(campaign.id),
        tenant_id=user.domain,
        ip_address=request.client.host if request.client else "",
        detail={"channel": payload.channel, "total": campaign.total, "ai_model": campaign.ai_model},
        commit=True,
    )
    return _detail(db, campaign)


def _detail(db: Session, campaign: Campaign) -> CampaignDetail:
    messages = (
        db.query(CampaignMessage)
        .filter(CampaignMessage.campaign_id == campaign.id)
        .order_by(CampaignMessage.id.asc())
        .limit(500)
        .all()
    )
    return CampaignDetail(
        **CampaignOut.model_validate(campaign).model_dump(),
        messages=[CampaignMessageOut.model_validate(message) for message in messages],
    )


@router.get("", response_model=list[CampaignOut])
def list_campaigns(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Campaign)
        .filter(Campaign.user_id == user.id)
        .order_by(Campaign.created_at.desc())
        .all()
    )


@router.get("/{campaign_id}", response_model=CampaignDetail)
def get_campaign(
    campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    campaign = (
        db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.user_id == user.id).first()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _detail(db, campaign)


@router.patch("/{campaign_id}/messages/{message_id}", response_model=CampaignMessageOut)
def edit_message(
    campaign_id: int,
    message_id: int,
    payload: CampaignMessageUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    message = (
        db.query(CampaignMessage)
        .filter(
            CampaignMessage.id == message_id,
            CampaignMessage.campaign_id == campaign_id,
            CampaignMessage.user_id == user.id,
        )
        .first()
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Campaign message not found")
    if payload.rendered_subject is not None:
        message.rendered_subject = payload.rendered_subject
    if payload.rendered_body is not None:
        message.rendered_body = payload.rendered_body
    if payload.approve:
        message.status = "approved"
    db.commit()
    db.refresh(message)
    return message


@router.post("/{campaign_id}/approve", response_model=CampaignDetail)
def approve_campaign(
    campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    campaign = (
        db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.user_id == user.id).first()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.query(CampaignMessage).filter(
        CampaignMessage.campaign_id == campaign_id, CampaignMessage.status == "pending_review"
    ).update({"status": "approved"}, synchronize_session=False)
    campaign.status = "approved"
    db.commit()
    db.refresh(campaign)
    log_event(
        db,
        action="campaign.approve",
        actor_user_id=user.id,
        resource_type="campaign",
        resource_id=str(campaign.id),
        tenant_id=user.domain,
        detail={},
        commit=True,
    )
    return _detail(db, campaign)


@router.post("/{campaign_id}/send", response_model=CampaignSendResult)
def send_campaign(
    campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    campaign = (
        db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.user_id == user.id).first()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")

    messages = (
        db.query(CampaignMessage)
        .filter(CampaignMessage.campaign_id == campaign_id, CampaignMessage.status == "approved")
        .all()
    )
    sent = failed = skipped = 0
    email_connection = db.query(EmailConnection).filter(EmailConnection.user_id == user.id).first()
    gateway = WechatyGateway()

    for message in messages:
        try:
            if campaign.channel == "email":
                if email_connection is None:
                    raise RuntimeError("no email connection configured")
                from ..security import decrypt_secret

                MailSender(
                    email_connection.smtp_host,
                    email_connection.smtp_port,
                    email_connection.email_address,
                    decrypt_secret(email_connection.secret_encrypted),
                ).send(
                    message.to_address,
                    message.rendered_subject or campaign.name,
                    message.rendered_body,
                )
                message.status = "sent"
                sent += 1
            elif campaign.channel in {"whatsapp", "wechat"}:
                if not settings.WHATSAPP_ENABLED:
                    raise RuntimeError("WhatsApp/WeChat channel is disabled")
                result = gateway.send_text(message.to_address, message.rendered_body)
                message.status = "sent"
                message.provider_id = str(result.get("id", ""))
                sent += 1
            else:  # linkedin -> manual queue
                message.status = "queued"
                skipped += 1
            message.sent_at = datetime.utcnow()
        except Exception as exc:  # noqa: BLE001 - record per-message failure
            message.status = "failed"
            message.error = str(exc)[:500]
            failed += 1

    campaign.sent_count += sent
    campaign.failed_count += failed
    campaign.status = "completed" if failed == 0 else "failed"
    db.commit()
    db.refresh(campaign)

    log_event(
        db,
        action="campaign.send",
        actor_user_id=user.id,
        resource_type="campaign",
        resource_id=str(campaign.id),
        status=campaign.status,
        tenant_id=user.domain,
        detail={"sent": sent, "failed": failed, "skipped": skipped},
        commit=True,
    )
    return CampaignSendResult(
        campaign_id=campaign.id, status=campaign.status, sent=sent, failed=failed, skipped=skipped
    )


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(
    campaign_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    campaign = (
        db.query(Campaign).filter(Campaign.id == campaign_id, Campaign.user_id == user.id).first()
    )
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.query(CampaignMessage).filter(CampaignMessage.campaign_id == campaign_id).delete(
        synchronize_session=False
    )
    db.delete(campaign)
    db.commit()
