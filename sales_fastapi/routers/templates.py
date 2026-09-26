"""Message template management (email / WhatsApp / LinkedIn / WeChat)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..governance.audit import log_event
from ..models import MessageTemplate, User
from ..outreach_templates import (
    CHANNELS,
    DEFAULT_TEMPLATES,
    FUNNEL_STAGES,
    SENDER,
    STRATEGIES,
)
from ..schemas import TemplateCreate, TemplateOut, TemplateUpdate
from ..security import get_current_user
from ..templating import variables_used

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("/meta")
def templates_meta(user: User = Depends(get_current_user)):
    return {
        "channels": CHANNELS,
        "strategies": STRATEGIES,
        "funnel_stages": FUNNEL_STAGES,
        "sender": SENDER,
    }


@router.get("", response_model=list[TemplateOut])
def list_templates(
    channel: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(MessageTemplate).filter(
        MessageTemplate.user_id.in_([user.id, 0]), MessageTemplate.is_active.is_(True)
    )
    if channel:
        query = query.filter(MessageTemplate.channel == channel)
    if strategy:
        query = query.filter(MessageTemplate.strategy == strategy)
    return query.order_by(MessageTemplate.updated_at.desc()).all()


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(
    payload: TemplateCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    variables = payload.variables or variables_used(payload.subject + " " + payload.body)
    template = MessageTemplate(
        user_id=user.id, **payload.model_dump(exclude={"variables"}), variables=variables
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    log_event(
        db,
        action="template.create",
        actor_user_id=user.id,
        resource_type="template",
        resource_id=str(template.id),
        tenant_id=user.domain,
        detail={"channel": template.channel},
        commit=True,
    )
    return template


@router.patch("/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    template = (
        db.query(MessageTemplate)
        .filter(MessageTemplate.id == template_id, MessageTemplate.user_id == user.id)
        .first()
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    changed = payload.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(template, field, value)
    if "subject" in changed or "body" in changed:
        template.variables = variables_used(template.subject + " " + template.body)
    db.commit()
    db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    template = (
        db.query(MessageTemplate)
        .filter(MessageTemplate.id == template_id, MessageTemplate.user_id == user.id)
        .first()
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    db.delete(template)
    db.commit()


@router.post("/seed")
def seed_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = {
        (row.name, row.channel)
        for row in db.query(MessageTemplate.name, MessageTemplate.channel)
        .filter(MessageTemplate.user_id == user.id)
        .all()
    }
    created = 0
    for item in DEFAULT_TEMPLATES:
        if (item["name"], item["channel"]) in existing:
            continue
        db.add(
            MessageTemplate(
                user_id=user.id,
                variables=variables_used(item["subject"] + " " + item["body"]),
                **item,
            )
        )
        created += 1
    db.commit()
    return {"created": created, "total": len(DEFAULT_TEMPLATES)}
