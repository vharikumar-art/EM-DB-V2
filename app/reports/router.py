import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.core.dependencies import (
    CurrentUser,
    get_current_user,
    resolve_employee_context,
)
from app.core.exceptions import ForbiddenException, NotFoundException
from app.database.mongodb import get_collection
from app.utils.response import to_object_id

router = APIRouter(prefix="/reports", tags=["Reports"])


def _employee_scope_query(employee_ids: str | list[str] | None, is_admin: bool) -> dict:
    if isinstance(employee_ids, list):
        return {"employeeId": {"$in": employee_ids}}
    if employee_ids is not None:
        return {"employeeId": employee_ids}
    if is_admin:
        return {}
    raise ForbiddenException("No employee data is available for this account")


# ── Email Master export ───────────────────────────────────────────────────────

EMAIL_MASTER_FIELDS = [
    "fullName", "email", "university", "website", "country", "state", "city",
    "domain", "industry", "designation", "phone", "linkedin",
    "uploadBatch", "isDuplicate", "createdAt",
]


@router.get("/email-master/export")
async def export_email_master_csv(
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Stream all email_master records for an employee as CSV."""
    target_id, is_admin = await resolve_employee_context(current_user, employeeId)
    query = _employee_scope_query(target_id, is_admin)
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
    "fullName", "email", "university", "country", "state", "city",
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
    profile_doc = await get_collection("profiles").find_one(
        {"_id": to_object_id(profileId)}, {"employeeId": 1}
    )
    if not profile_doc:
        raise NotFoundException("Profile not found")
    profile_employee_id = str(profile_doc.get("employeeId") or "")
    allowed_employee_ids, is_admin = await resolve_employee_context(
        current_user, profile_employee_id
    )
    if isinstance(allowed_employee_ids, list):
        allowed_ids = {str(employee_id) for employee_id in allowed_employee_ids}
    elif allowed_employee_ids is not None:
        allowed_ids = {str(allowed_employee_ids)}
    else:
        allowed_ids = set()
    if profile_employee_id not in allowed_ids and not (
        is_admin and allowed_employee_ids is None
    ):
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
    target_id, is_admin = await resolve_employee_context(current_user, employeeId)

    col = get_collection("campaigns")
    query = _employee_scope_query(target_id, is_admin)

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
