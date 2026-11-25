from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so the path is correct regardless of
# which working directory the server is launched from.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_DEVELOPMENT_SECRET_DEFAULTS = frozenset(
    {
        "insecure-dev-secret-change-me",
        "dev-password-encryption-key-123456",
        "change-this-to-a-random-jwt-secret",
        "change-this-to-a-random-encryption-key",
    }
)
_MIN_PRODUCTION_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    APP_NAME: str = "Email Marketing Management System"
    ENV: str = "development"
    PROFILE_PICTURE_STORAGE_DIR: str = "./uploads/profile-pictures-test"

    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "email_marketing_db"

    JWT_SECRET_KEY: str = "insecure-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: str = "http://localhost:5173"
    EMAIL_MASTER_DROPDOWN_CACHE_KEY: str = "email_master:dropdown_options"
    EMAIL_MASTER_DROPDOWN_CACHE_TTL_SECONDS: int = 1800


    PASSWORD_ENCRYPTION_KEY: str = "dev-password-encryption-key-123456"

    RATE_LIMIT_PER_MINUTE: int = 100

    @property
    def profile_picture_storage_path(self) -> Path:
        path = Path(self.PROFILE_PICTURE_STORAGE_DIR)
        if path.is_absolute():
            return path
        return _ENV_FILE.parent / path

    # LLM settings removed - using simple placeholder replacement only

    # Gmail SMTP defaults (used as fallback; per-account creds stored in email_accounts)
    GMAIL_SMTP_HOST: str = "smtp.gmail.com"
    GMAIL_SMTP_PORT: int = 587

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.ENV.strip().casefold() == "development":
            return self

        invalid_secrets = [
            field_name
            for field_name, secret in (
                ("JWT_SECRET_KEY", self.JWT_SECRET_KEY),
                ("PASSWORD_ENCRYPTION_KEY", self.PASSWORD_ENCRYPTION_KEY),
            )
            if (
                len(secret.strip()) < _MIN_PRODUCTION_SECRET_LENGTH
                or secret.strip().casefold() in _DEVELOPMENT_SECRET_DEFAULTS
            )
        ]
        if invalid_secrets:
            raise ValueError(
                "For non-development environments, set "
                f"{', '.join(invalid_secrets)} to non-placeholder secrets "
                f"of at least {_MIN_PRODUCTION_SECRET_LENGTH} characters"
            )
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()