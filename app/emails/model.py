from datetime import datetime, timezone
from typing import Any


def build_email_document(employee_id: str, upload_batch: str, is_duplicate: bool, row: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "employeeId": employee_id,
        "fullName": row.get("fullName", ""),
        "email": row["email"],
        "company": row.get("company", ""),
        "website": row.get("website", ""),
        "country": row.get("country", ""),
        "state": row.get("state", ""),
        "city": row.get("city", ""),
        "domain": row.get("domain", ""),
        "industry": row.get("industry", ""),
        "designation": row.get("designation", ""),
        "phone": row.get("phone", ""),
        "linkedin": row.get("linkedin", ""),
        "citation": row.get("citation", ""),
        "mailSource": row.get("mailSource", ""),
        "uploadBatch": upload_batch,
        "isDuplicate": is_duplicate,
        "createdAt": now,
    }
