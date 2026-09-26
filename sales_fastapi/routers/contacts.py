from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..governance.audit import log_event
from ..importer import normalise_record, records_from_bytes
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
            Contact.company.ilike(like) | Contact.name.ilike(like) | Contact.email.ilike(like)
        )
    return query.order_by(Contact.created_at.desc()).all()


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(
    payload: ContactCreate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(Contact).filter(Contact.user_id == user.id, Contact.email == payload.email).first()
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

    log_event(
        db,
        action="contact.create",
        actor_user_id=user.id,
        resource_type="contact",
        resource_id=str(contact.id),
        tenant_id=user.domain,
        ip_address=request.client.host if request.client else "",
        detail={"source": contact.source, "intent": contact.intent},
        commit=True,
    )
    return contact


@router.get("/stats")
def contact_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = db.query(Contact).filter(Contact.user_id == user.id)

    def group(column):
        rows = base.with_entities(column, func.count(Contact.id)).group_by(column).all()
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
    contact = db.query(Contact).filter(Contact.id == contact_id, Contact.user_id == user.id).first()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: int,
    payload: ContactUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = db.query(Contact).filter(Contact.id == contact_id, Contact.user_id == user.id).first()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    changed = payload.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(contact, field, value)
    db.commit()
    db.refresh(contact)
    log_event(
        db,
        action="contact.update",
        actor_user_id=user.id,
        resource_type="contact",
        resource_id=str(contact.id),
        tenant_id=user.domain,
        ip_address=request.client.host if request.client else "",
        detail={"fields": sorted(changed.keys())},
        commit=True,
    )
    return contact


@router.delete("/{contact_id}", status_code=204)
def delete_contact(
    contact_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    contact = db.query(Contact).filter(Contact.id == contact_id, Contact.user_id == user.id).first()
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")
    db.delete(contact)
    db.commit()
    log_event(
        db,
        action="contact.delete",
        actor_user_id=user.id,
        resource_type="contact",
        resource_id=str(contact_id),
        tenant_id=user.domain,
        ip_address=request.client.host if request.client else "",
        detail={},
        commit=True,
    )


# --------------------------------------------------------------------------
# File / GCS import
# --------------------------------------------------------------------------
def _insert_records(
    db: Session, user: User, records: list[dict], *, source: str, gcs_path: str = ""
) -> tuple[int, int]:
    """Insert normalised records for a user, skipping duplicates and blanks."""
    imported = skipped = 0
    for record in records:
        normalised = normalise_record(record)
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
        db.add(Contact(user_id=user.id, source=source, gcs_path=gcs_path, **normalised))
        imported += 1
    return imported, skipped


@router.post("/upload")
async def upload_contacts(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    gcs_prefix: str = Form(default=""),
    gcs_bucket: str = Form(default=""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload one or more CSV/Excel/VCF/JSON files, and/or import a GCS prefix.

    A user may attach multiple files; each supported file is parsed and merged
    into their own contact list. Optionally a GCS prefix can be synced in the
    same call.
    """
    imported = skipped = gcs_imported = gcs_skipped = 0

    for upload in files:
        if not upload.filename:
            continue
        raw = await upload.read()
        records = records_from_bytes(upload.filename, raw)
        file_imported, file_skipped = _insert_records(db, user, records, source="upload")
        imported += file_imported
        skipped += file_skipped

    gcs_scanned = 0
    if gcs_prefix.strip():
        gcs = GCSStorage(bucket_name=gcs_bucket.strip() or None)
        if not gcs.available:
            raise HTTPException(status_code=503, detail="GCS is not available")
        blobs = gcs.list_contacts(prefix=gcs_prefix.strip())
        gcs_scanned = len(blobs)
        for blob in blobs:
            raw = gcs.download_blob(blob["name"])
            if not raw:
                continue
            records = records_from_bytes(blob["name"], raw)
            done, missed = _insert_records(db, user, records, source="gcs", gcs_path=blob["name"])
            gcs_imported += done
            gcs_skipped += missed

    db.commit()
    total_imported = imported + gcs_imported
    log_event(
        db,
        action="contact.upload",
        actor_user_id=user.id,
        resource_type="contact",
        tenant_id=user.domain,
        ip_address=request.client.host if request.client else "",
        detail={
            "files": len(files),
            "gcs_prefix": gcs_prefix,
            "imported": total_imported,
        },
        commit=True,
    )
    return {
        "files": len(files),
        "imported": imported,
        "skipped": skipped,
        "gcs_scanned": gcs_scanned,
        "gcs_imported": gcs_imported,
        "gcs_skipped": gcs_skipped,
        "total_imported": total_imported,
    }


@router.post("/import/gcs")
def import_from_gcs(
    prefix: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prefix = prefix or settings.GCS_PATH_CONTACTS
    allowed_prefix = settings.GCS_PATH_CONTACTS.rstrip("/") + "/"
    if prefix != settings.GCS_PATH_CONTACTS and not prefix.startswith(allowed_prefix):
        raise HTTPException(status_code=400, detail="GCS prefix is outside the contacts namespace")
    gcs = GCSStorage()
    if not gcs.available:
        raise HTTPException(
            status_code=503,
            detail="GCS is not available (missing credentials / package)",
        )
    blobs = gcs.list_contacts(prefix=prefix)

    imported = skipped = 0
    for blob in blobs:
        raw = gcs.download_blob(blob["name"])
        if not raw:
            continue
        records = records_from_bytes(blob["name"], raw)
        done, missed = _insert_records(db, user, records, source="gcs", gcs_path=blob["name"])
        imported += done
        skipped += missed
    db.commit()
    return {"scanned": len(blobs), "imported": imported, "skipped": skipped, "prefix": prefix}
