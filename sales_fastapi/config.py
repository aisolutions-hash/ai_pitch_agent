from functools import lru_cache

from pydantic import Field, model_validator
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
    GMAIL_OAUTH_ENABLED: bool = Field(default=True, alias="GMAIL_OAUTH_ENABLED")
    GOOGLE_OAUTH_REDIRECT_URI: str = Field(default="", alias="GOOGLE_OAUTH_REDIRECT_URI")
    FRONTEND_URL: str = Field(default="http://localhost:5173", alias="FRONTEND_URL")
    AUTH_DEV_MODE: bool = Field(default=False, alias="AUTH_DEV_MODE")
    # When dev mode is enabled, restrict it to these emails (comma-separated).
    AUTH_DEV_ALLOWED_EMAILS: str = Field(default="", alias="AUTH_DEV_ALLOWED_EMAILS")

    # --- SMTP / IMAP ---
    SMTP_HOST: str = Field(default="", alias="SMTP_HOST")
    SMTP_PORT: int = Field(default=587, alias="SMTP_PORT")
    SMTP_USER: str = Field(default="", alias="SMTP_USER")
    SMTP_PASSWORD: str = Field(default="", alias="SMTP_PASSWORD")
    IMAP_HOST: str = Field(default="", alias="IMAP_HOST")
    IMAP_PORT: int = Field(default=993, alias="IMAP_PORT")
    IMAP_USER: str = Field(default="", alias="IMAP_USER")

    # --- AI ---
    GEMMA_MODEL: str = Field(default="gemma-4-27b-it", alias="GEMMA_MODEL")
    GEMINI_API_KEY: str = Field(default="", alias="GEMINI_API_KEY")

    # --- WhatsApp ---
    WHATSAPP_API_KEY: str = Field(default="", alias="WHATSAPP_API_KEY")
    WHATSAPP_PHONE_NUMBER_ID: str = Field(default="", alias="WHATSAPP_PHONE_NUMBER_ID")

    # --- Wechaty gateway (WhatsApp/WeChat via Node service) ---
    WHATSAPP_ENABLED: bool = Field(default=False, alias="WHATSAPP_ENABLED")
    WECHATY_GATEWAY_URL: str = Field(default="http://localhost:8788", alias="WECHATY_GATEWAY_URL")
    WECHATY_GATEWAY_TOKEN: str = Field(default="", alias="WECHATY_GATEWAY_TOKEN")
    WECHATY_WEBHOOK_SECRET: str = Field(default="", alias="WECHATY_WEBHOOK_SECRET")
    WECHATY_TIMEOUT_SECONDS: int = Field(default=15, alias="WECHATY_TIMEOUT_SECONDS")

    # --- LinkedIn / Reddit / YouTube (Google-secured APIs) ---
    LINKEDIN_CLIENT_ID: str = Field(default="", alias="LINKEDIN_CLIENT_ID")
    LINKEDIN_CLIENT_SECRET: str = Field(default="", alias="LINKEDIN_CLIENT_SECRET")
    REDDIT_CLIENT_ID: str = Field(default="", alias="REDDIT_CLIENT_ID")
    REDDIT_CLIENT_SECRET: str = Field(default="", alias="REDDIT_CLIENT_SECRET")
    YOUTUBE_API_KEY: str = Field(default="", alias="YOUTUBE_API_KEY")

    # --- Event workbook / WhatsApp scheduling ---
    # The workbook is not shipped in the container, so imports are uploaded
    # through the API; EVENTS_WORKBOOK_NAME is the local-data fallback name.
    EVENTS_WORKBOOK_NAME: str = Field(default="events list.xlsx", alias="EVENTS_WORKBOOK_NAME")
    EVENTS_LOCAL_DIR: str = Field(default="data", alias="EVENTS_LOCAL_DIR")
    EVENTS_MAX_RECIPIENTS_PER_MESSAGE: int = Field(
        default=200, alias="EVENTS_MAX_RECIPIENTS_PER_MESSAGE"
    )
    EVENTS_DEFAULT_LEAD_MINUTES: int = Field(default=60, alias="EVENTS_DEFAULT_LEAD_MINUTES")

    # --- Security ---
    SECRET_KEY: str = Field(default="change-this-secret", alias="SECRET_KEY")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60, alias="ACCESS_TOKEN_EXPIRE_MINUTES")

    # --- Runtime guardrails ---
    ALLOWED_HOSTS: str = Field(default="localhost,127.0.0.1,testserver", alias="ALLOWED_HOSTS")
    MAX_REQUEST_BYTES: int = Field(default=1_048_576, alias="MAX_REQUEST_BYTES")
    RATE_LIMIT_ENABLED: bool = Field(default=False, alias="RATE_LIMIT_ENABLED")
    AUTH_RATE_LIMIT: int = Field(default=10, alias="AUTH_RATE_LIMIT")
    API_RATE_LIMIT: int = Field(default=120, alias="API_RATE_LIMIT")

    # --- Data governance ---
    GOVERNANCE_ENABLED: bool = Field(default=True, alias="GOVERNANCE_ENABLED")
    PII_REDACTION_ENABLED: bool = Field(default=True, alias="PII_REDACTION_ENABLED")
    AUDIT_LOG_ENABLED: bool = Field(default=True, alias="AUDIT_LOG_ENABLED")
    RETENTION_DAYS_AUDIT: int = Field(default=365, alias="RETENTION_DAYS_AUDIT")
    RETENTION_DAYS_CONTACTS: int = Field(default=730, alias="RETENTION_DAYS_CONTACTS")

    # --- Cost-optimised SLM routing ---
    LLM_ENABLED: bool = Field(default=False, alias="LLM_ENABLED")
    LLM_TIMEOUT_SECONDS: int = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    LLM_MAX_INPUT_CHARS: int = Field(default=20_000, alias="LLM_MAX_INPUT_CHARS")
    LLM_MAX_OUTPUT_CHARS: int = Field(default=40_000, alias="LLM_MAX_OUTPUT_CHARS")
    LLM_MONTHLY_TOKEN_BUDGET: int = Field(default=5_000_000, alias="LLM_MONTHLY_TOKEN_BUDGET")
    LLM_ENFORCE_BUDGET: bool = Field(default=True, alias="LLM_ENFORCE_BUDGET")
    LLM_LOCAL_BASE_URL: str = Field(default="http://localhost:11434", alias="LLM_LOCAL_BASE_URL")
    LLM_LOCAL_NANO_MODEL: str = Field(default="qwen2.5:0.5b", alias="LLM_LOCAL_NANO_MODEL")
    LLM_LOCAL_MODEL: str = Field(default="qwen2.5:3b", alias="LLM_LOCAL_MODEL")
    LLM_LOCAL_MEDIUM_MODEL: str = Field(default="llama3.1:8b", alias="LLM_LOCAL_MEDIUM_MODEL")
    LLM_CLOUD_FLASH_MODEL: str = Field(default="gemini-2.0-flash", alias="LLM_CLOUD_FLASH_MODEL")
    LLM_CLOUD_MODEL: str = Field(default="gemini-2.5-pro", alias="LLM_CLOUD_MODEL")
    LLM_GEMMA_MODEL: str = Field(default="gemma-4-27b-it", alias="LLM_GEMMA_MODEL")

    # --- CORS ---
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:8000", alias="CORS_ORIGINS"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()]

    @property
    def google_signin_configured(self) -> bool:
        """True only for a real OAuth web client id (not the .env.example placeholder)."""
        client_id = (self.GOOGLE_CLIENT_ID or "").strip()
        if not client_id.endswith(".apps.googleusercontent.com"):
            return False
        if client_id.startswith("your-client-id"):
            return False
        return True

    @property
    def google_gmail_oauth_configured(self) -> bool:
        return bool(
            self.GMAIL_OAUTH_ENABLED
            and self.google_signin_configured
            and self.GOOGLE_CLIENT_SECRET.strip()
            and self.GOOGLE_OAUTH_REDIRECT_URI.strip()
        )

    @property
    def auth_dev_allowed_list(self) -> list[str]:
        return [
            email.strip().lower()
            for email in self.AUTH_DEV_ALLOWED_EMAILS.split(",")
            if email.strip()
        ]

    @model_validator(mode="after")
    def validate_security_settings(self):
        if len(self.SECRET_KEY) < 32 or self.SECRET_KEY == "change-this-secret":
            raise ValueError("SECRET_KEY must be at least 32 characters and non-default")
        if self.ACCESS_TOKEN_EXPIRE_MINUTES < 5 or self.ACCESS_TOKEN_EXPIRE_MINUTES > 1440:
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be between 5 and 1440")
        if self.MAX_REQUEST_BYTES < 16_384:
            raise ValueError("MAX_REQUEST_BYTES must be at least 16384")
        if self.ENV.lower() == "production":
            if self.AUTH_DEV_MODE and not self.auth_dev_allowed_list:
                raise ValueError(
                    "AUTH_DEV_MODE must be false in production unless "
                    "AUTH_DEV_ALLOWED_EMAILS restricts it to specific emails"
                )
            required = {
                "GOOGLE_CLIENT_ID": self.GOOGLE_CLIENT_ID,
                "GOOGLE_ALLOWED_DOMAINS": self.GOOGLE_ALLOWED_DOMAINS,
                "GOOGLE_CLOUD_PROJECT": self.GOOGLE_CLOUD_PROJECT,
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise ValueError(f"Missing production security settings: {', '.join(missing)}")
            if not self.CORS_ORIGINS.strip() or "*" in self.cors_origin_list:
                raise ValueError("Production CORS_ORIGINS must list explicit origins")
            if not self.allowed_host_list or "*" in self.allowed_host_list:
                raise ValueError("Production ALLOWED_HOSTS must be restricted")
            if not self.PII_REDACTION_ENABLED:
                raise ValueError("PII_REDACTION_ENABLED must be true in production")
            if not self.AUDIT_LOG_ENABLED:
                raise ValueError("AUDIT_LOG_ENABLED must be true in production")
            if self.WHATSAPP_ENABLED and not self.WECHATY_GATEWAY_TOKEN:
                raise ValueError("WECHATY_GATEWAY_TOKEN is required when WHATSAPP_ENABLED is true")
            if self.WHATSAPP_ENABLED and not self.WECHATY_WEBHOOK_SECRET:
                raise ValueError("WECHATY_WEBHOOK_SECRET is required when WHATSAPP_ENABLED is true")
        if self.LLM_MONTHLY_TOKEN_BUDGET < 1:
            raise ValueError("LLM_MONTHLY_TOKEN_BUDGET must be positive")
        if self.LLM_MAX_INPUT_CHARS < 1024:
            raise ValueError("LLM_MAX_INPUT_CHARS must be at least 1024")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
