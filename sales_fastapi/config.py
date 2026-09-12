import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    PROJECT_NAME: str = "Kalisoft AI Sales Pipeline"
    VERSION: str = "1.0.0"
    ENV: str = "development"

    # --- Google Cloud / GCS ---
    GOOGLE_CLOUD_PROJECT: str = Field(default="", alias="GOOGLE_CLOUD_PROJECT")
    GCS_BUCKET_CONTACTS: str = Field(default="kalisoftai-datahub", alias="GCS_BUCKET_CONTACTS")
    GCS_PATH_CONTACTS: str = Field(default="all-sales-contacts-data", alias="GCS_PATH_CONTACTS")

    # --- Database ---
    # If DATABASE_URL is set it wins. Otherwise the app builds a Postgres URL
    # from the parts below, and falls back to local SQLite if nothing is set.
    DATABASE_URL: str = Field(default="", alias="DATABASE_URL")
    POSTGRES_HOST: str = Field(default="", alias="POSTGRES_HOST")
    POSTGRES_PORT: int = Field(default=5432, alias="POSTGRES_PORT")
    POSTGRES_DB: str = Field(default="sales_pipeline", alias="POSTGRES_DB")
    POSTGRES_USER: str = Field(default="postgres", alias="POSTGRES_USER")
    POSTGRES_PASSWORD: str = Field(default="", alias="POSTGRES_PASSWORD")
    CLOUD_SQL_CONNECTION_NAME: str = Field(default="", alias="CLOUD_SQL_CONNECTION_NAME")
    SQLITE_PATH: str = Field(default="sales_pipeline.db", alias="SQLITE_PATH")

    # --- Redis ---
    REDIS_URL: str = Field(default="", alias="REDIS_URL")
    REDIS_HOST: str = Field(default="localhost", alias="REDIS_HOST")
    REDIS_PORT: int = Field(default=6379, alias="REDIS_PORT")
    REDIS_DB: int = Field(default=0, alias="REDIS_DB")

    # --- Google Sign-In / OAuth ---
    GOOGLE_CLIENT_ID: str = Field(default="", alias="GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str = Field(default="", alias="GOOGLE_CLIENT_SECRET")
    GOOGLE_ALLOWED_DOMAINS: str = Field(default="", alias="GOOGLE_ALLOWED_DOMAINS")
    AUTH_DEV_MODE: bool = Field(default=True, alias="AUTH_DEV_MODE")

    # --- SMTP / IMAP ---
    SMTP_HOST: str = Field(default="", alias="SMTP_HOST")
    SMTP_PORT: int = Field(default=587, alias="SMTP_PORT")
    SMTP_USER: str = Field(default="", alias="SMTP_USER")
    SMTP_PASSWORD: str = Field(default="", alias="SMTP_PASSWORD")
    IMAP_HOST: str = Field(default="", alias="IMAP_HOST")
    IMAP_PORT: int = Field(default=993, alias="IMAP_PORT")
    IMAP_USER: str = Field(default="", alias="IMAP_USER")

    # --- AI ---
    GEMMA_MODEL: str = Field(default="gemma-3-27b-it", alias="GEMMA_MODEL")
    GEMINI_API_KEY: str = Field(default="", alias="GEMINI_API_KEY")

    # --- WhatsApp ---
    WHATSAPP_API_KEY: str = Field(default="", alias="WHATSAPP_API_KEY")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="", alias="WHATSAPP_PHONE_NUMBER_ID")

    # --- LinkedIn / Reddit ---
    LINKEDIN_CLIENT_ID: str = Field(default="", alias="LINKEDIN_CLIENT_ID")
    LINKEDIN_CLIENT_SECRET: str = Field(default="", alias="LINKEDIN_CLIENT_SECRET")
    REDDIT_CLIENT_ID: str = Field(default="", alias="REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET: str = Field(default="", alias="REDDIT_CLIENT_SECRET")

    # --- Security ---
    SECRET_KEY: str = Field(default="change-this-secret", alias="SECRET_KEY")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # --- CORS ---
    CORS_ORIGINS: str = Field(default="http://localhost:3000,http://localhost:8000", alias="CORS_ORIGINS")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
