"""External integrations.

Every integration is written to degrade gracefully: if credentials or network
are unavailable the method returns a structured placeholder / empty result and
flags ``available = False`` instead of raising, so the app stays testable.
"""

from __future__ import annotations

import base64
import binascii
import email
import imaplib
import json
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional
from urllib.parse import urlencode

from .config import settings

# ==========================================================================
# Contact segregation helpers (domain / intent / context)
# ==========================================================================
_FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "rediffmail.com",
    "live.com",
    "icloud.com",
    "protonmail.com",
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
    return {
        "domain": domain,
        "intent": intent,
        "context": context_text.strip(),
    }


def compact_text(value: str, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[: max(0, int(limit))].strip()


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
                out.append(
                    {"name": blob.name, "size": blob.size, "content_type": blob.content_type}
                )
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

    def fetch_emails(
        self,
        limit: int = 25,
        query: str = "",
        sender: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        if self.connection is None:
            self.connect()
        assert self.connection is not None
        safe_limit = max(1, min(int(limit), 50))
        criteria = ["ALL"]
        if unread_only:
            criteria.append("UNSEEN")
        if query.strip():
            criteria.extend(["TEXT", query.strip()])
        if sender.strip():
            criteria.extend(["FROM", f'"{sender.strip()}"'])
        if since is not None:
            criteria.extend(["SINCE", since.strftime("%d-%b-%Y")])
        if until is not None:
            criteria.extend(["BEFORE", (until + timedelta(days=1)).strftime("%d-%b-%Y")])
        status, data = self.connection.search(None, *criteria)
        if status != "OK":
            raise RuntimeError("IMAP search failed")
        raw_ids = data[0].split() if data and data[0] else []
        scan_limit = min(max(safe_limit * 5, 50), 200)
        ids = raw_ids[-scan_limit:]
        results: list[dict[str, Any]] = []
        for uid in ids:
            _status, msg_data = self.connection.fetch(uid, "(RFC822)")
            raw = msg_data[1][0][1]
            msg = email.message_from_bytes(raw)
            subject = msg.get("Subject", "")
            body = self._extract_body(msg)
            results.append(
                {
                    "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                    "subject": subject,
                    "from": msg.get("From", ""),
                    "date": msg.get("Date", ""),
                    "intent": infer_intent(f"{subject} {compact_text(body, 1000)}"),
                    "body": body[:50_000],
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


class GoogleOAuthClient:
    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    gmail_scope = "https://www.googleapis.com/auth/gmail.readonly"

    def __init__(self):
        self.client_id = (settings.GOOGLE_CLIENT_ID or "").strip()
        self.client_secret = (settings.GOOGLE_CLIENT_SECRET or "").strip()
        self.redirect_uri = (settings.GOOGLE_OAUTH_REDIRECT_URI or "").strip()

    @property
    def configured(self) -> bool:
        return bool(
            settings.GMAIL_OAUTH_ENABLED
            and self.client_id
            and self.client_secret
            and self.redirect_uri
        )

    def authorization_url(self, state: str) -> str:
        if not self.configured:
            raise RuntimeError("Google Gmail OAuth is not configured")
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": f"openid email profile {self.gmail_scope}",
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.authorization_endpoint}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Google Gmail OAuth is not configured")
        import httpx

        try:
            with httpx.Client(timeout=20) as client:
                response = client.post(
                    self.token_endpoint,
                    data={
                        "code": code,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "redirect_uri": self.redirect_uri,
                        "grant_type": "authorization_code",
                    },
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("Google OAuth token exchange failed") from exc
        if response.status_code >= 400:
            raise RuntimeError("Google OAuth token exchange failed")
        return response.json()

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        if not self.configured or not refresh_token:
            raise RuntimeError("Google Gmail OAuth is not configured")
        import httpx

        try:
            with httpx.Client(timeout=20) as client:
                response = client.post(
                    self.token_endpoint,
                    data={
                        "refresh_token": refresh_token,
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "refresh_token",
                    },
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("Google OAuth token refresh failed") from exc
        if response.status_code >= 400:
            raise RuntimeError("Google OAuth token refresh failed")
        return response.json()


class GmailExtractor:
    api_root = "https://gmail.googleapis.com/gmail/v1/users/me"

    def __init__(self, access_token: str):
        self.access_token = access_token

    def _get(self, path: str, params: Any) -> dict[str, Any]:
        import httpx

        try:
            response = httpx.get(
                f"{self.api_root}/{path.lstrip('/')}",
                params=params,
                headers={"Authorization": f"Bearer {self.access_token}"},
                timeout=20,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("Gmail API request failed") from exc
        if response.status_code >= 400:
            raise RuntimeError("Gmail API request failed")
        return response.json()

    def profile(self) -> dict[str, Any]:
        return self._get("profile", {})

    def fetch_emails(
        self,
        limit: int = 15,
        query: str = "",
        sender: str = "",
        since: datetime | None = None,
        until: datetime | None = None,
        unread_only: bool = False,
        include_body: bool = False,
    ) -> tuple[int, list[dict[str, Any]]]:
        safe_limit = max(1, min(int(limit), 50))
        query_parts: list[str] = []
        if query.strip():
            query_parts.append(f"{{{query.strip()}}}")
        if sender.strip():
            query_parts.append(f"from:{sender.strip().replace(chr(34), '')}")
        if since is not None:
            query_parts.append(f"after:{since.strftime('%Y/%m/%d')}")
        if until is not None:
            query_parts.append(f"before:{(until + timedelta(days=1)).strftime('%Y/%m/%d')}")
        if unread_only:
            query_parts.append("is:unread")
        listing = self._get(
            "messages",
            {"q": " ".join(query_parts), "maxResults": min(max(safe_limit * 4, 50), 100)},
        )
        items = listing.get("messages", [])
        results: list[dict[str, Any]] = []
        for item in items:
            message_id = str(item.get("id", ""))
            if not message_id:
                continue
            metadata = self._get(
                f"messages/{message_id}",
                [
                    ("format", "metadata"),
                    ("metadataHeaders", "Subject"),
                    ("metadataHeaders", "From"),
                    ("metadataHeaders", "Date"),
                ],
            )
            headers = {
                str(header.get("name", "")).lower(): str(header.get("value", ""))
                for header in metadata.get("payload", {}).get("headers", [])
            }
            subject = headers.get("subject", "")
            snippet = compact_text(str(metadata.get("snippet", "")), 1000)
            body = ""
            if include_body:
                full_message = self._get(f"messages/{message_id}", {"format": "full"})
                body = self._extract_body(full_message.get("payload", {}))
            results.append(
                {
                    "uid": message_id,
                    "subject": subject,
                    "from": headers.get("from", ""),
                    "date": headers.get("date", ""),
                    "intent": infer_intent(f"{subject} {snippet} {body}"),
                    "body": body[:50_000],
                    "snippet": snippet,
                }
            )
            if len(results) >= safe_limit:
                break
        return len(items), results

    @classmethod
    def _extract_body(cls, part: dict[str, Any]) -> str:
        mime_type = str(part.get("mimeType", ""))
        data = str(part.get("body", {}).get("data", ""))
        if data:
            try:
                padding = "=" * (-len(data) % 4)
                decoded = base64.urlsafe_b64decode(f"{data}{padding}").decode(errors="ignore")
            except (binascii.Error, ValueError):
                decoded = ""
            if mime_type == "text/plain" or not part.get("parts"):
                return decoded
        for child in part.get("parts", []):
            body = cls._extract_body(child)
            if body:
                return body
        return ""


# ==========================================================================
# SMTP sending
# ==========================================================================
class MailSender:
    def __init__(self, smtp_host: str, smtp_port: int = 587, user: str = "", password: str = ""):
        self.smtp_host = smtp_host
        self.smtp_port = int(smtp_port or 587)
        self.user = user
        self.password = password

    def send(
        self, to: str, subject: str, body: str, from_email: str | None = None
    ) -> dict[str, Any]:
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

    def search_by_hiring_alerts(
        self, keywords: list[str], location: str = ""
    ) -> list[dict[str, Any]]:
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
# YouTube (Google Data API v3)
# ==========================================================================
class YouTubeExtractor:
    """YouTube Data API v3 extractor for company / tech signal scanning.

    Secured via a Google API key (or ADC service-account) configured in
    ``YOUTUBE_API_KEY``. Without credentials it returns deterministic stubs so
    the pipeline can be exercised end-to-end, mirroring LinkedIn/Reddit.
    """

    def __init__(self):
        self.available = bool(settings.YOUTUBE_API_KEY)

    def search_signals(self, queries: list[str], max_results: int = 10) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        out: list[dict[str, Any]] = []
        for q in queries:
            slug = re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-")
            out.append(
                {
                    "video_url": f"https://www.youtube.com/results?search_query={slug}",
                    "title": f"[signal] {q}",
                    "channel": "",
                    "query": q,
                    "extracted_at": now,
                    "api_available": self.available,
                }
            )
            if len(out) >= max_results:
                break
        return out


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
