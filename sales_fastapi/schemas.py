from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- Auth ----------
class GoogleLoginIn(BaseModel):
    id_token: str = Field(..., description="Google Identity Services ID token (JWT)")


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    picture: str
    domain: str


# ---------- Contacts ----------
class ContactBase(BaseModel):
    company: str = ""
    name: str = ""
    email: str
    phone: str = ""
    domain: str = ""
    intent: str = ""
    context: str = ""
    linkedin_company: str = ""
    linkedin_profiles: list[str] = Field(default_factory=list)
    address: str = ""
    purchase_contact_name: str = ""
    purchase_contact_role: str = ""
    purchase_contact_email: str = ""
    purchase_contact_phone: str = ""
    tags: list[str] = Field(default_factory=list)
    notes: str = ""


class ContactCreate(ContactBase):
    source: str = "manual"
    gcs_path: str = ""


class ContactUpdate(BaseModel):
    company: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    domain: Optional[str] = None
    intent: Optional[str] = None
    context: Optional[str] = None
    linkedin_company: Optional[str] = None
    linkedin_profiles: Optional[list[str]] = None
    address: Optional[str] = None
    purchase_contact_name: Optional[str] = None
    purchase_contact_role: Optional[str] = None
    purchase_contact_email: Optional[str] = None
    purchase_contact_phone: Optional[str] = None
    tags: Optional[list[str]] = None
    notes: Optional[str] = None


class ContactOut(ContactBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    gcs_path: str
    created_at: datetime
    updated_at: datetime


# ---------- Email ----------
class EmailConnectionCreate(BaseModel):
    email_address: str
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    password: str = Field(default="", description="App password; stored encrypted")


class EmailConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email_address: str
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    is_connected: bool


class SendMailIn(BaseModel):
    to: str
    subject: str
    body: str


# ---------- LinkedIn / Reddit ----------
class LinkedInSearchIn(BaseModel):
    keywords: list[str] = Field(default_factory=lambda: ["procurement", "scm", "hiring"])
    location: str = ""


class RedditSearchIn(BaseModel):
    subreddits: list[str] = Field(default_factory=lambda: ["jobs", "recruiting"])
    keywords: list[str] = Field(default_factory=lambda: ["hiring", "procurement"])


# ---------- WhatsApp ----------
class WhatsAppSendIn(BaseModel):
    phone_number: str
    message: str
