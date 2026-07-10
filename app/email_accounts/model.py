from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AccountType(str, Enum):
    GMAIL_SMTP = "gmail_smtp"      # Gmail with App Password via SMTP
    SMTP = "smtp"                  # Generic SMTP (Office365, Zoho, etc.)


def build_email_account_document(
    employee_id: str,
    email: str,
    account_type: AccountType,
    display_name: str,
    encrypted_password: str,
    smtp_host: str,
    smtp_port: int,
    use_tls: bool,
) -> dict[str, Any]:
    """
    Stores sending credentials for a Gmail / SMTP account.

    The raw app-password is NEVER stored.  Only the Fernet-encrypted token
    (using the same PASSWORD_ENCRYPTION_KEY as the rest of the app) is persisted.
    """
    now = datetime.now(timezone.utc)
    return {
        "employeeId": employee_id,
        "email": email,
        "accountType": account_type.value,
        "displayName": display_name,
        # Fernet-encrypted app password — decrypted in-memory only at send time
        "encryptedPassword": encrypted_password,
        # SMTP settings
        "smtpHost": smtp_host,
        "smtpPort": smtp_port,
        "useTls": use_tls,
        # Health tracking
        "isActive": True,
        "lastUsedAt": None,
        "lastErrorAt": None,
        "lastError": None,
        "sendCount": 0,
        "createdAt": now,
        "updatedAt": now,
    }
