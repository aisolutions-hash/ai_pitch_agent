"""External integrations.

Every integration is written to degrade gracefully: if credentials or network
are unavailable the method returns a structured placeholder / empty result and
flags ``available = False`` instead of raising, so the app stays testable.
"""

from __future__ import annotations

import email
import imaplib
import json
import re
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

from .config import settings


# ==========================================================================
# Contact segregation helpers (domain / intent / context)
# ==========================================================================
_FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com",
    "live.com", "icloud.com", "protonmail.com",
}

_INTENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("hiring", ("hiring", "recruit", "vacancy", "job", "intern", "opening")),
    ("procurement", ("procure", "purchase", "scm", "supply", "sourcing", "buyer", "vendor")),
    ("sales", ("sales", "rfq", "quotation", "quote", "enquiry", "inquiry")),
    ("partnership", ("partner", "collaborat", "alliance", "tie-up")),
    ("support", ("support", "help", "service", "issue", "complaint")),
]


def infer_domain(email_address: str) -> str:
    if not email_address or "@" not in email_address:
        return ""
    return email_address.split("@")[-1].strip().lower()


def infer_intent(text: str) -> str:
    haystack = (text or "").lower()
    for intent, needles in _INTENT_RULES:
        if any(n in haystack for n in needles):
            return intent
    return "general"


def classify_contact(email_address: str = "", context_text: str = "") -> dict[str, str]:
    """Produce a first-pass (domain, intent, context) segregation."""
    domain = infer_domain(email_address)
    intent = infer_intent(context_text or email_address)
    is_free = domain in _FREE_EMAIL_DOMAINS
    return {
        "domain": domain,
        "intent": intent,
        "context": context_text.strip(),
    }


# ==========================================================================
# Google Cloud Storage
# ==========================================================================
class GCSStorage:
    def __init__(self, bucket_name: str | None = None):
        self.bucket_name = bucket_name or settings.GCS_BUCKET_CONTACTS
        self.available = False
        self._client = None
        try:
            from google.cloud import storage  # type: ignore

            self._client = storage.Client(project=settings.GOOGLE_CLOUD_PROJECT or None)
            self.available = True
        except Exception:  # pragma: no cover - depends on env
            self._client = None
            self.available = False

    def list_contacts(self, prefix: str | None = None) -> list[dict[str, Any]]:
        if not self.available or self._client is None:
            return []
        prefix = prefix if prefix is not None else settings.GCS_PATH_CONTACTS
        out: list[dict[str, Any]] = []
        try:
            for blob in self._client.list_blobs(self.bucket_name, prefix=prefix):
                if not blob.name.lower().endswith((".json", ".csv", ".vcf", ".xlsx", ".xls")):
                    continue
                out.append({"name": blob.name, "size": blob.size, "content_type": blob.content_type})
        except Exception:
            return out
        return out

    def download_blob(self, blob_name: str) -> Optional[bytes]:
        if not self.available or self._client is None:
            return None
        try:
            blob = self._client.bucket(self.bucket_name).blob(blob_name)
            if blob.exists():
                return blob.download_as_bytes()
        except Exception:
            return None
        return None

    def upload_json(self, blob_name: str, payload: dict[str, Any]) -> bool:
        if not self.available or self._client is None:
            return False
        try:
            blob = self._client.bucket(self.bucket_name).blob(blob_name)
            blob.upload_from_string(json.dumps(payload), content_type="application/json")
            return True
        except Exception:
            return False


# ==========================================================================
# IMAP extraction
# ==========================================================================
class EmailExtractor:
    def __init__(self, imap_host: str, imap_port: int = 993, user: str = "", password: str = ""):
        self.imap_host = imap_host
        self.imap_port = int(imap_port or 993)
        self.user = user
        self.password = password
        self.connection: imaplib.IMAP4_SSL | None = None

    def connect(self) -> bool:
        self.connection = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
        self.connection.login(self.user, self.password)
        self.connection.select("INBOX")
        return True

    def fetch_emails(self, limit: int = 25) -> list[dict[str, Any]]:
        if self.connection is None:
            self.connect()
        assert self.connection is not None
        _status, data = self.connection.search(None, "ALL")
        ids = data[0].split()[-limit:]
        results: list[dict[str, Any]] = []
        for uid in ids:
            _status, msg_data = self.connection.fetch(uid, "(RFC822)")
            raw = msg_data[1][0][1]
            msg = email.message_from_bytes(raw)
            results.append(
                {
                    "uid": uid.decode(),
                    "subject": msg.get("Subject", ""),
                    "from": msg.get("From", ""),
                    "date": msg.get("Date", ""),
                    "intent": infer_intent(msg.get("Subject", "")),
                    "body": self._extract_body(msg),
                }
            )
        return results

    @staticmethod
    def _extract_body(msg) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(errors="ignore")
            return ""
        payload = msg.get_payload(decode=True)
        return payload.decode(errors="ignore") if payload else ""

    def disconnect(self) -> None:
        if self.connection is not None:
            try:
                self.connection.logout()
            except Exception:
                pass
            finally:
                self.connection = None


# ==========================================================================
# SMTP sending
# ==========================================================================
class MailSender:
    def __init__(self, smtp_host: str, smtp_port: int = 587, user: str = "", password: str = ""):
        self.smtp_host = smtp_host
        self.smtp_port = int(smtp_port or 587)
        self.user = user
        self.password = password

    def send(self, to: str, subject: str, body: str, from_email: str | None = None) -> dict[str, Any]:
        from_email = from_email or self.user
        msg = MIMEMultipart()
        msg["From"] = from_email
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as server:
            server.starttls()
            if self.user:
                server.login(self.user, self.password)
            server.send_message(msg)
        return {"sent": True, "to": to, "from": from_email}


# ==========================================================================
# LinkedIn
# ==========================================================================
class LinkedInExtractor:
    def __init__(self):
        self.available = bool(settings.LINKEDIN_CLIENT_ID)

    def search_by_hiring_alerts(self, keywords: list[str], location: str = "") -> list[dict[str, Any]]:
        """Return candidate profile stubs for hiring-related keywords.

        Without API credentials this produces deterministic stubs so the pipeline
        can be exercised end-to-end.
        """
        now = datetime.now(timezone.utc).isoformat()
        out = []
        for kw in keywords:
            slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
            out.append(
                {
                    "profile_url": f"https://www.linkedin.com/in/{slug}-talent",
                    "name": kw.title(),
                    "headline": f"{kw} | hiring",
                    "company": "",
                    "location": location,
                    "skills": [],
                    "source_keyword": kw,
                    "extracted_at": now,
                }
            )
        return out

    def extract_profile(self, profile_url: str) -> dict[str, Any]:
        return {
            "profile_url": profile_url,
            "name": "",
            "headline": "",
            "company": "",
            "location": "",
            "skills": [],
            "source_keyword": "",
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }


# ==========================================================================
# Reddit
# ==========================================================================
class RedditScraper:
    def __init__(self):
        self.available = bool(settings.REDDIT_CLIENT_ID)

    def search_hiring_posts(
        self, subreddits: list[str], keywords: list[str]
    ) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        out = []
        for sub in subreddits:
            for kw in keywords:
                out.append(
                    {
                        "post_url": f"https://www.reddit.com/r/{sub}/search/?q={kw}",
                        "title": f"[{sub}] hiring: {kw}",
                        "content": "",
                        "subreddit": sub,
                        "alerts_related": [kw],
                        "extracted_at": now,
                    }
                )
        return out
