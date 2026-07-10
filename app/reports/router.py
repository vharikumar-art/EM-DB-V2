import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.dependencies import CurrentUser, get_current_user
from app.database.mongodb import get_collection
from app.employees.service import get_employee_by_user_id

router = APIRouter(prefix="/reports", tags=["Reports"])

# ── Email Master export ───────────────────────────────────────────────────────

EMAIL_MASTER_FIELDS = [
    "fullName", "email", "company", "website", "country", "state", "city",
    "domain", "industry", "designation", "phone", "linkedin",
    "uploadBatch", "isDuplicate", "createdAt",
]


@router.get("/email-master/export")
async def export_email_master_csv(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stream all email_master records for an employee as CSV."""
    if current_user.role == "admin":
        target_id = employeeId
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_id = employee["id"]

    query = {"employeeId": target_id} if target_id else {}
    col = get_collection("email_master")

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EMAIL_MASTER_FIELDS, extrasaction="ignore")
    writer.writeheader()
    async for doc in col.find(query).sort("createdAt", -1):
        writer.writerow({k: str(doc.get(k, "")) for k in EMAIL_MASTER_FIELDS})

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=email_master_export.csv"},
    )


# ── Profile emails export ─────────────────────────────────────────────────────

PROFILE_EMAIL_FIELDS = [
    "fullName", "email", "company", "country", "state", "city",
    "domain", "industry", "designation",
    "sendStatus", "threadId", "messageId", "sentDate",
    "errorMessage", "notes", "retryCount", "createdAt",
]


@router.get("/profile-emails/export")
async def export_profile_emails_csv(
    profileId: str = Query(...),
    sendStatus: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stream profile_emails for a profile as CSV (optionally filtered by status)."""
    if current_user.role != "admin":
        employee = await get_employee_by_user_id(current_user.user_id)
        # Ownership check — employee can only export their own profiles
        col_check = get_collection("profiles")
        from app.utils.response import to_object_id
        profile_doc = await col_check.find_one({"_id": to_object_id(profileId)})
        if not profile_doc or str(profile_doc.get("employeeId")) != employee["id"]:
            from app.core.exceptions import ForbiddenException
            raise ForbiddenException("Access denied")

    col = get_collection("profile_emails")
    query: dict = {"profileId": profileId}
    if sendStatus:
        query["sendStatus"] = sendStatus

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PROFILE_EMAIL_FIELDS, extrasaction="ignore")
    writer.writeheader()
    async for doc in col.find(query).sort("createdAt", 1):
        writer.writerow({k: str(doc.get(k, "")) for k in PROFILE_EMAIL_FIELDS})

    buffer.seek(0)
    filename = f"profile_emails_{profileId}_{sendStatus or 'all'}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Campaign report ───────────────────────────────────────────────────────────

@router.get("/campaigns/export")
async def export_campaigns_csv(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stream campaign history as CSV."""
    if current_user.role == "admin":
        target_id = employeeId
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_id = employee["id"]

    col = get_collection("campaigns")
    query = {"employeeId": target_id} if target_id else {}

    fields = [
        "campaignName", "profileId", "employeeId", "status",
        "totalEmails", "pending", "sent", "failed", "skipped", "replies",
        "startedAt", "completedAt", "createdAt",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    async for doc in col.find(query).sort("createdAt", -1):
        writer.writerow({k: str(doc.get(k, "")) for k in fields})

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=campaigns_export.csv"},
    )
