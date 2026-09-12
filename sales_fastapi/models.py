from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    picture: Mapped[str] = mapped_column(String(512), default="")
    domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Contact(Base):
    """A sales contact, optionally enriched with company / SCM details."""

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("user_id", "email", name="uq_contact_user_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, default=0)

    # Core
    company: Mapped[str] = mapped_column(String(255), default="", index=True)
    name: Mapped[str] = mapped_column(String(255), default="", index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    phone: Mapped[str] = mapped_column(String(64), default="")

    # Segregation axes
    domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    intent: Mapped[str] = mapped_column(String(64), default="", index=True)
    context: Mapped[str] = mapped_column(Text, default="")

    # Enrichment
    linkedin_company: Mapped[str] = mapped_column(String(512), default="")
    linkedin_profiles: Mapped[list] = mapped_column(JSON, default=list)
    address: Mapped[str] = mapped_column(Text, default="")
    purchase_contact_name: Mapped[str] = mapped_column(String(255), default="")
    purchase_contact_role: Mapped[str] = mapped_column(String(255), default="")
    purchase_contact_email: Mapped[str] = mapped_column(String(320), default="")
    purchase_contact_phone: Mapped[str] = mapped_column(String(64), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")

    # Provenance
    source: Mapped[str] = mapped_column(String(32), default="manual", index=True)
    gcs_path: Mapped[str] = mapped_column(String(512), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class EmailConnection(Base):
    __tablename__ = "email_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    email_address: Mapped[str] = mapped_column(String(320), index=True)
    imap_host: Mapped[str] = mapped_column(String(255), default="")
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    smtp_host: Mapped[str] = mapped_column(String(255), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    # Fernet-encrypted app password (never returned by the API).
    secret_encrypted: Mapped[str] = mapped_column(Text, default="")
    is_connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LinkedInProfile(Base):
    __tablename__ = "linkedin_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    profile_url: Mapped[str] = mapped_column(String(512), index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    headline: Mapped[str] = mapped_column(String(512), default="")
    company: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    source_keyword: Mapped[str] = mapped_column(String(255), default="")
    extracted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RedditPost(Base):
    __tablename__ = "reddit_posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    post_url: Mapped[str] = mapped_column(String(512), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    subreddit: Mapped[str] = mapped_column(String(128), default="")
    alerts_related: Mapped[list] = mapped_column(JSON, default=list)
    extracted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    phone_number: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
