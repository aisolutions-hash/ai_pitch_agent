"""Database engine / session factory.

Resolution order:
1. DATABASE_URL env var (used by tests -> sqlite, and by Cloud Run -> postgres)
2. CLOUD_SQL_CONNECTION_NAME -> Postgres over the Cloud SQL unix socket
3. POSTGRES_HOST -> plain Postgres TCP
4. Fallback -> local SQLite file (zero-config developer mode)
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def _build_url() -> str:
    if settings.DATABASE_URL:
        return settings.DATABASE_URL

    if settings.CLOUD_SQL_CONNECTION_NAME:
        return (
            "postgresql+psycopg2://"
            f"{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
            f"@/{settings.POSTGRES_DB}"
            f"?host=/cloudsql/{settings.CLOUD_SQL_CONNECTION_NAME}"
        )

    if settings.POSTGRES_HOST:
        return (
            "postgresql+psycopg2://"
            f"{settings.POSTGRES_USER}:{settings.POSTGRES_PASSWORD}"
            f"@{settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
        )

    return f"sqlite:///{settings.SQLITE_PATH}"


DATABASE_URL = _build_url()

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
