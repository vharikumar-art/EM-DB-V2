from datetime import datetime, timezone
from typing import Any


def build_email_master_document(
    upload_batch: str,
    is_duplicate: bool,
    uploaded_by: str,
    uploaded_by_name: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    """
    Permanent email record (GLOBAL POOL).  Never mutated after creation except for
    usedInProfiles (updated when a profile list is generated).
    
    Global: All employees can see and use this email.
    Tracking: uploadedBy records who contributed the data.
    """
    now = datetime.now(timezone.utc)
    return {
        # Upload tracking
        "uploadBatch": upload_batch,
        "uploadedBy": uploaded_by,
        "uploadedByName": uploaded_by_name,
        "uploadedDate": now,
        # Duplicate handling (global)
        "isDuplicate": is_duplicate,
        "duplicateOf": None,  # Will be set if this is a duplicate
        # Contact fields
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
        # Profile usage tracking
        # List of { profileId, employeeId, usedDate }
        "usedInProfiles": [],
        
        # Employee assignment tracking (NEW FIELDS)
        "inProfileEmails": False,        # YES/NO - Has it been added to any profile?
        "usedByEmployeeId": None,        # Employee ID who claimed this email
        "usedByEmployeeName": None,      # Employee name who claimed this email
        "assignedDate": None,            # When assigned to employee
        
        "createdAt": now,
        "updatedAt": now,
    }
