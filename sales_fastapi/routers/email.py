from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EmailConnection, User
from ..schemas import EmailConnectionCreate, EmailConnectionOut, SendMailIn
from ..security import decrypt_secret, encrypt_secret, get_current_user
from ..services import EmailExtractor, MailSender

router = APIRouter(prefix="/email", tags=["email"])


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


@router.get("/connections/{connection_id}/inbox")
def read_inbox(
    connection_id: int,
    limit: int = 15,
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
    extractor = EmailExtractor(
        conn.imap_host, conn.imap_port, conn.email_address, decrypt_secret(conn.secret_encrypted)
    )
    try:
        messages = extractor.fetch_emails(limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"IMAP error: {exc}") from exc
    finally:
        extractor.disconnect()
    return {"count": len(messages), "messages": messages}


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
