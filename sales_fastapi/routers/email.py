from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EmailConnection, User
from ..schemas import (
    EmailConnectionCreate,
    EmailConnectionOut,
    EmailFetchIn,
    EmailFetchOut,
    EmailMessageContextOut,
    SendMailIn,
)
from ..security import decrypt_secret, encrypt_secret, get_current_user
from ..services import EmailExtractor, MailSender, compact_text

router = APIRouter(prefix="/email", tags=["email"])


def _owned_connection(connection_id: int, user: User, db: Session) -> EmailConnection:
    connection = (
        db.query(EmailConnection)
        .filter(EmailConnection.id == connection_id, EmailConnection.user_id == user.id)
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


def _email_context(message: dict, payload: EmailFetchIn) -> EmailMessageContextOut | None:
    subject = str(message.get("subject", ""))
    sender = str(message.get("from") or message.get("sender") or "")
    body = str(message.get("body", ""))
    snippet = str(message.get("snippet", ""))
    haystack = f"{subject} {sender} {body} {snippet}".lower()
    if payload.query.strip() and payload.query.strip().lower() not in haystack:
        return None
    if payload.sender.strip() and payload.sender.strip().lower() not in sender.lower():
        return None
    if payload.intent and message.get("intent") != payload.intent:
        return None
    context = compact_text(body or str(message.get("snippet", "")), payload.context_chars)
    result = {
        "uid": str(message.get("uid", "")),
        "subject": subject,
        "sender": sender,
        "date": str(message.get("date", "")),
        "intent": str(message.get("intent", "general")),
        "context": context if payload.include_context else "",
    }
    if payload.include_body:
        result["body"] = body[:10_000]
    return EmailMessageContextOut(**result)


def _fetch_filters(payload: EmailFetchIn) -> dict:
    return {
        "query": payload.query,
        "sender": payload.sender,
        "intent": payload.intent,
        "since": payload.since.isoformat() if payload.since else None,
        "until": payload.until.isoformat() if payload.until else None,
        "unread_only": payload.unread_only,
    }


@router.get("/connections", response_model=list[EmailConnectionOut])
def list_connections(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(EmailConnection).filter(EmailConnection.user_id == user.id).all()


@router.post("/connections", response_model=EmailConnectionOut, status_code=201)
def add_connection(
    payload: EmailConnectionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = EmailConnection(
        user_id=user.id,
        email_address=payload.email_address,
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        secret_encrypted=encrypt_secret(payload.password),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


@router.post("/connections/{connection_id}/test")
def test_connection(
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = (
        db.query(EmailConnection)
        .filter(EmailConnection.id == connection_id, EmailConnection.user_id == user.id)
        .first()
    )
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    password = decrypt_secret(conn.secret_encrypted)
    result: dict[str, str] = {}

    extractor = EmailExtractor(conn.imap_host, conn.imap_port, conn.email_address, password)
    try:
        extractor.connect()
        result["imap"] = "connected"
    except Exception as exc:  # noqa: BLE001
        result["imap"] = f"failed: {exc}"
    finally:
        extractor.disconnect()

    sender = MailSender(conn.smtp_host, conn.smtp_port, conn.email_address, password)
    try:
        sender.send(conn.email_address, "Kalisoft connection test", "SMTP OK")
        result["smtp"] = "connected"
    except Exception as exc:  # noqa: BLE001
        result["smtp"] = f"failed: {exc}"

    conn.is_connected = result["imap"] == "connected" and result["smtp"] == "connected"
    conn.last_checked_at = datetime.utcnow()
    db.commit()
    return {"connection_id": conn.id, "is_connected": conn.is_connected, **result}


@router.post(
    "/connections/{connection_id}/fetch",
    response_model=EmailFetchOut,
    response_model_exclude_none=True,
)
def fetch_connection(
    connection_id: int,
    payload: EmailFetchIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = _owned_connection(connection_id, user, db)
    extractor = EmailExtractor(
        conn.imap_host, conn.imap_port, conn.email_address, decrypt_secret(conn.secret_encrypted)
    )
    try:
        messages = extractor.fetch_emails(
            limit=payload.limit,
            query=payload.query,
            sender=payload.sender,
            since=payload.since,
            until=payload.until,
            unread_only=payload.unread_only,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"IMAP error: {exc}") from exc
    finally:
        extractor.disconnect()
    context_messages = [
        context for message in messages if (context := _email_context(message, payload)) is not None
    ][: payload.limit]
    return EmailFetchOut(
        connection_id=conn.id,
        count=len(context_messages),
        scanned=len(messages),
        messages=context_messages,
        filters=_fetch_filters(payload),
        options={
            "include_context": payload.include_context,
            "include_body": payload.include_body,
            "context_chars": payload.context_chars,
        },
    )


@router.get(
    "/connections/{connection_id}/inbox",
    response_model=EmailFetchOut,
    response_model_exclude_none=True,
)
def read_inbox(
    connection_id: int,
    limit: int = Query(default=15, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return fetch_connection(connection_id, EmailFetchIn(limit=limit), user, db)


@router.post("/send")
def send_mail(
    payload: SendMailIn,
    connection_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = (
        db.query(EmailConnection)
        .filter(EmailConnection.id == connection_id, EmailConnection.user_id == user.id)
        .first()
    )
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    sender = MailSender(
        conn.smtp_host, conn.smtp_port, conn.email_address, decrypt_secret(conn.secret_encrypted)
    )
    try:
        result = sender.send(payload.to, payload.subject, payload.body, conn.email_address)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"SMTP error: {exc}") from exc
    return result
