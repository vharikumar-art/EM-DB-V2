from datetime import datetime, timezone
from typing import Any


def build_setting_document(key: str, values: list[str] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    normalized_values = [str(v).strip() for v in (values or []) if str(v).strip()]
    return {
        "key": key,
        "values": normalized_values,
        "createdAt": now,
        "updatedAt": now,
    }
