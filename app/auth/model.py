from datetime import datetime, timezone
from typing import Any

REVOKED_TOKENS_COLLECTION = "revoked_tokens"


def build_revoked_token_document(token: str, user_id: str) -> dict[str, Any]:
    return {
        "token": token,
        "userId": user_id,
        "revokedAt": datetime.now(timezone.utc),
    }
