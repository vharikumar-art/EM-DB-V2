import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_development_allows_local_secret_defaults():
    settings = Settings(_env_file=None, ENV="development")

    assert settings.ENV == "development"


def test_non_development_rejects_missing_or_development_secrets():
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            ENV="production",
            JWT_SECRET_KEY="insecure-dev-secret-change-me",
            PASSWORD_ENCRYPTION_KEY="dev-password-encryption-key-123456",
        )

    message = str(error.value)
    assert "JWT_SECRET_KEY" in message
    assert "PASSWORD_ENCRYPTION_KEY" in message
    assert "insecure-dev-secret-change-me" not in message


def test_non_development_rejects_example_placeholders():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ENV="Production",
            JWT_SECRET_KEY="change-this-to-a-random-jwt-secret",
            PASSWORD_ENCRYPTION_KEY="change-this-to-a-random-encryption-key",
        )


def test_non_development_accepts_long_configured_secrets():
    settings = Settings(
        _env_file=None,
        ENV="production",
        JWT_SECRET_KEY="jwt-secret-value-" + "a" * 40,
        PASSWORD_ENCRYPTION_KEY="encryption-secret-" + "b" * 40,
    )

    assert settings.ENV == "production"
