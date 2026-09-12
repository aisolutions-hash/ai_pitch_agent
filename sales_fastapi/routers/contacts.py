from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Contact, User
from ..schemas import ContactCreate, ContactOut, ContactUpdate
from ..security import get_current_user
from ..services import GCSStorage, classify_contact

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=list[ContactOut])
def list_contacts(
    domain: str | None = None,
    intent: str | None = None,
    context: str | None = None,
    source: str | None = None,
    q: str | None = Query(default=None, description="free-text search"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Contact).filter(Contact.user_id == user.id)
    if domain:
        query = query.filter(Contact.domain.ilike(f"%{domain}%"))
    if intent:
        query = query.filter(Contact.intent.ilike(f"%{intent}%"))
    if context:
        query = query.filter(Contact.context.ilike(f"%{context}%"))
    if source:
        query = query.filter(Contact.source == source)
    if q:
        like = f"%{q}%"
        query = query.filter(
            Contact.company.ilike(like)
            | Contact.name.ilike(like)
            | Contact.email.ilike(like)
        )
    return query.order_by(Contact.created_at.desc()).all()


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(
    payload: ContactCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(Contact)
        .filter(Contact.user_id == user.id, Contact.email == payload.email)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Contact with this email already exists")

    data = payload.model_dump()
    # Auto-segregate anything the caller did not explicitly set.
    verdict = classify_contact(payload.email, payload.context or payload.notes)
    data["domain"] = data.get("domain") or verdict["domain"]
    data["intent"] = data.get("intent") or verdict["intent"]

    contact = Contact(user_id=user.id, **data)
    db.add(contact)
    db.commit()
    db.refresh(contact)

    # Best-effort mirror into GCS (never blocks the API response on failure).
    path = contact.gcs_path or f"{settings.GCS_PATH_CONTACTS}/users/{user.id}/{contact.id}.json"
    if GCSStorage().upload_json(
        path,
        {
            "company": contact.company,
            "name": contact.name,
            "email": contact.email,
            "domain": contact.domain,
            "intent": contact.intent,
            "context": contact.context,
        },
    ):
        contact.gcs_path = path
        db.commit()
        db.refresh(contact)
    return contact


@router.get("/stats")
def contact_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = db.query(Contact).filter(Contact.user_id == user.id)

    def group(column):
        rows = (
            base.with_entities(column, func.count(Contact.id))
            .group_by(column)
            .all()
        )
        return {(value or "(none)"): count for value, count in rows}

    return {
        "total": base.count(),
        "by_domain": group(Contact.domain),
        "by_intent": group(Contact.intent),
        "by_source": group(Contact.source),
    }


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = (
        db.query(Contact)
        .filter(Contact.id == contact_id, Contact.user_id == user.id)
        .first()
    )
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = (
        db.query(Contact)
        .filter(Contact.id == contact_id, Contact.user_id == user.id)
        .first()
    )
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    return contact


@router.delete("/{contact_id}", status_code=204)
def delete_contact(
    contact_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = (
        db.query(Contact)
        .filter(Contact.id == contact_id, Contact.user_id == user.id)
        .first()
    )
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()


# --------------------------------------------------------------------------
# GCS import
# --------------------------------------------------------------------------
def _records_from_bytes(name: str, raw: bytes) -> list[dict]:
    lower = name.lower()
    if lower.endswith(".json"):
        try:
            parsed = json.loads(raw.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, dict):
            # support {"contacts": [...]}
            return parsed.get("contacts", [parsed])
        if isinstance(parsed, list):
            return parsed
        return []
    if lower.endswith(".csv"):
        text = raw.decode("utf-8", errors="ignore")
        return list(csv.DictReader(io.StringIO(text)))
    return []


def _normalise(record: dict) -> dict | None:
    def pick(*keys):
        for key in keys:
            for record_key in record:
                if record_key and record_key.strip().lower() == key:
                    value = record[key]
                    if value:
                        return str(value).strip()
        return ""

    email_address = pick("email", "email (company / division)", "e-mail", "mail")
    company = pick("company", "organisation", "organization")
    if not email_address and not company:
        return None
    verdict = classify_contact(email_address, company)
    return {
        "company": company,
        "name": pick("name", "contact", "contact name"),
        "email": email_address or f"unknown-{abs(hash(company))}@placeholder.local",
        "phone": pick("phone", "contact (phone)"),
        "address": pick("address", "address (ahmednagar unit)"),
        "linkedin_company": pick("linkedin", "linkedin (company / key scm profile)"),
        "purchase_contact_name": pick("purchase / scm contact (name, role)"),
        "purchase_contact_email": pick("purchase contact details (email / phone)"),
        "domain": verdict["domain"],
        "intent": verdict["intent"],
        "context": company,
        "source": "gcs",
    }


@router.post("/import/gcs")
def import_from_gcs(
    prefix: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    gcs = GCSStorage()
    if not gcs.available:
        raise HTTPException(
            status_code=503,
            detail="GCS is not available (missing credentials / package)",
        )
    prefix = prefix or settings.GCS_PATH_CONTACTS
    blobs = gcs.list_contacts(prefix=prefix)

    imported = skipped = 0
    for blob in blobs:
        raw = gcs.download_blob(blob["name"])
        if not raw:
            continue
        for record in _records_from_bytes(blob["name"], raw):
            normalised = _normalise(record)
            if not normalised:
                skipped += 1
                continue
            exists = (
                db.query(Contact)
                .filter(Contact.user_id == user.id, Contact.email == normalised["email"])
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(Contact(user_id=user.id, gcs_path=blob["name"], **normalised))
            imported += 1
    db.commit()
    return {"scanned": len(blobs), "imported": imported, "skipped": skipped, "prefix": prefix}
