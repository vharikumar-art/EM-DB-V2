import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _get_fernet_key() -> str:
    digest = hashlib.sha256(settings.PASSWORD_ENCRYPTION_KEY.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


cipher = Fernet(_get_fernet_key())


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def encrypt_password(password: str) -> str:
    return cipher.encrypt(password.encode("utf-8")).decode("utf-8")


def decrypt_password(token: str) -> str:
    return cipher.decrypt(token.encode("utf-8")).decode("utf-8")


def _create_token(
    subject: str, 
    role: str, 
    token_type: Literal["access", "refresh"], 
    expires_delta: timedelta,
    employee_id: str | None = None
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    # Add employeeId if provided (for non-admin users)
    if employee_id:
        payload["employee_id"] = employee_id
    
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str, role: str, employee_id: str | None = None) -> str:
    return _create_token(
        subject, role, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), employee_id
    )


def create_refresh_token(subject: str, role: str, employee_id: str | None = None) -> str:
    return _create_token(
        subject, role, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS), employee_id
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
