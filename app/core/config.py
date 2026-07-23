from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Email Marketing Management System"
    ENV: str = "development"

    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "email_marketing_db"

    JWT_SECRET_KEY: str = "insecure-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: str = "http://localhost:3000"


    PASSWORD_ENCRYPTION_KEY: str = "dev-password-encryption-key-123456"

    RATE_LIMIT_PER_MINUTE: int = 100

    # LLM settings removed - using simple placeholder replacement only

    # Gmail SMTP defaults (used as fallback; per-account creds stored in email_accounts)
    GMAIL_SMTP_HOST: str = "smtp.gmail.com"
    GMAIL_SMTP_PORT: int = 587

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()
