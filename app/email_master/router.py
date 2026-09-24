import csv
import io
from datetime import date
from typing import List, Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.core.dependencies import CurrentUser, get_current_user, require_admin, require_super_admin, require_write_access
from app.core.exceptions import BadRequestException
from app.email_master import service
from app.email_master.schema import MarkReplyRequest, UpdateReplyRequest, UploadResult
from app.schemas.common import ApiResponse, PaginationParams
from app.utils.pagination import pagination_params

router = APIRouter(prefix="/email-master", tags=["Email Master"])

_ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")


@router.post("/upload", response_model=ApiResponse[UploadResult])
async def upload_emails(
    file: UploadFile = File(...),
    insertDuplicates: bool = Query(default=False),
    mailSource: str | None = Query(default=None, description="Mail source: Google Scholar, University, Other"),
    current_user: CurrentUser = Depends(require_write_access),
):
    """Upload email CSV/Excel file to global pool. Tracks who uploaded."""
    if not any(file.filename.lower().endswith(ext) for ext in _ALLOWED_EXTENSIONS):
        raise BadRequestException("Only .csv, .xlsx, and .xls files are supported")

    file_bytes = await file.read()
    
    # Get employee name from database
    from app.employees.service import get_employee_by_user_id
    try:
        employee = await get_employee_by_user_id(current_user.user_id)
        uploaded_by_name = employee.get("name") or current_user.user_id
    except:
        # Fallback to user_id if employee not found
        uploaded_by_name = current_user.user_id
    
    result = await service.upload_file(
        uploaded_by_id=current_user.user_id,
        uploaded_by_name=uploaded_by_name,
        file_bytes=file_bytes,
        filename=file.filename,
        insert_duplicates=insertDuplicates,
        mail_source=mailSource,
    )
    # Invalidate the dropdown cache so the new upload's countries/domains
    # appear immediately the next time the dropdown endpoint is called.
    service.invalidate_dropdown_cache()
    return ApiResponse(message="File processed", data=result)


@router.get("/dropdown-options", response_model=ApiResponse)
async def get_dropdown_options(
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get dropdown filter options from GLOBAL pool."""
    options = await service.get_dropdown_options()
    return ApiResponse(message="Dropdown options fetched", data=options)


@router.get("/download")
async def download_emails(
    format: Literal["csv", "xlsx"] = Query(default="csv", description="Download format"),
    country: str | None = Query(default=None),
    state: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    university: str | None = Query(default=None),
    mailSource: str | None = Query(default=None),
    search: str | None = Query(default=None),
    includeDuplicates: bool = Query(default=True),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Download the global email-master pool as CSV or Excel."""
    query: dict = {}
    and_filters: list[dict] = []
    if country:
        query["country"] = country
    if state:
        query["state"] = state
    if domain:
        and_filters.append({"$or": [{"domain": domain}, {"domain_group": domain}]})
    if university:
        query["university"] = {"$regex": university, "$options": "i"}
    if mailSource:
        query["mailSource"] = mailSource
    if not includeDuplicates:
        query["isDuplicate"] = False
    if search:
        and_filters.append({"$or": [
            {"email": {"$regex": search, "$options": "i"}},
            {"fullName": {"$regex": search, "$options": "i"}},
            {"university": {"$regex": search, "$options": "i"}},
            {"domain": {"$regex": search, "$options": "i"}},
            {"domain_group": {"$regex": search, "$options": "i"}},
            {"country": {"$regex": search, "$options": "i"}},
        ]})
    if and_filters:
        query["$and"] = and_filters

    fields = [
        "fullName", "email", "university", "website", "country", "state",
        "city", "domain", "domain_group", "industry", "designation", "phone",
        "linkedin", "citation", "mailSource", "uploadBatch", "isDuplicate",
        "uploadedByName", "createdAt",
    ]
    master = service.get_collection(service.COLLECTION)
    rows = []
    async for doc in master.find(query).sort("createdAt", -1):
        rows.append({field: str(doc.get(field, "")) for field in fields})

    if format == "xlsx":
        buffer = io.BytesIO()
        pd.DataFrame(rows, columns=fields).to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=email_master.xlsx"},
        )

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=email_master.csv"},
    )


@router.get("/stats/uploaders", response_model=ApiResponse)
async def get_uploader_stats(
    current_user: CurrentUser = Depends(require_super_admin),
):
    """SUPER ADMIN ONLY: Get upload contribution statistics."""
    stats = await service.get_uploader_stats()
    return ApiResponse(message="Uploader statistics", data=stats)


@router.post("/count-filtered", response_model=ApiResponse)
async def count_filtered_emails(
    filters: dict,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Count emails matching filters from GLOBAL pool."""
    result = await service.count_filtered_emails(filters)
    return ApiResponse(message="Filtered email count", data=result)


@router.post("/replies", response_model=ApiResponse)
async def mark_email_reply(
    payload: MarkReplyRequest,
    current_user: CurrentUser = Depends(require_write_access),
):
    """Mark all matching email-master records as having received a reply."""
    record = await service.mark_email_reply(
        email=str(payload.email),
        reason=payload.reason,
        custom_reason=payload.customReason,
        marked_by=current_user.user_id,
        marked_by_name=await service.get_user_display_name(current_user.user_id),
    )
    return ApiResponse(message="Email reply marked", data=record)


@router.get("/replies", response_model=ApiResponse)
async def list_email_replies(
    search: str | None = Query(default=None),
    reason: str | None = Query(default=None),
    replyMarkedByName: str | None = Query(default=None),
    updatedTime: str | None = Query(default=None),
    updatedStartDate: date | None = Query(default=None),
    updatedEndDate: date | None = Query(default=None),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List email-master records that have received a reply."""
    result = await service.list_email_replies(
        params=params,
        search=search,
        user_id=current_user.user_id,
        role=current_user.role,
        reason=reason,
        reply_marked_by_name=replyMarkedByName,
        updated_time=updatedTime,
        updated_start_date=updatedStartDate,
        updated_end_date=updatedEndDate,
    )
    options = await service.get_reply_filter_options(
        user_id=current_user.user_id,
        role=current_user.role,
    )
    return ApiResponse(message="Email replies fetched", data=result, options=options)


@router.patch("/replies/{email_id}", response_model=ApiResponse)
async def update_email_reply(
    email_id: str,
    payload: UpdateReplyRequest,
    current_user: CurrentUser = Depends(require_write_access),
):
    """Edit or clear reply tracking for one email-master record."""
    record = await service.update_email_reply(
        email_id=email_id,
        payload=payload.model_dump(exclude_unset=True),
        marked_by=current_user.user_id,
        role=current_user.role,
    )
    return ApiResponse(message="Email reply updated", data=record)


@router.get("/{email_id}", response_model=ApiResponse)
async def get_email(
    email_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get email record from GLOBAL pool."""
    record = await service.get_email(email_id)
    return ApiResponse(message="Email record fetched", data=record)


@router.delete("/{email_id}", response_model=ApiResponse)
async def delete_email(
    email_id: str,
    current_user: CurrentUser = Depends(require_super_admin),
):
    """SUPER ADMIN ONLY: Delete email from GLOBAL pool."""
    await service.delete_email(email_id)
    return ApiResponse(message="Email deleted")


@router.post("/admin/clear-all", response_model=ApiResponse)
async def clear_all_emails(
    current_user: CurrentUser = Depends(require_super_admin),
):
    """SUPER ADMIN ONLY: Delete ALL emails from email_master table. WARNING: Irreversible!"""
    result = await service.clear_all_emails()
    return ApiResponse(message="Email master cleared", data=result)


@router.get("", response_model=ApiResponse)
async def list_emails(
    country: List[str] = Query(default=[]),
    state: List[str] = Query(default=[]),
    domain: List[str] = Query(default=[]),
    university: List[str] = Query(default=[]),
    uploadedBy: List[str] = Query(default=[]),
    usedByEmployee: List[str] = Query(default=[]),
    mailSource: List[str] = Query(default=[]),
    search: str | None = Query(default=None),
    includeDuplicates: bool = Query(default=True),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List emails from GLOBAL pool with filters.
    
    All filter params support multi-selection:
    - Repeat the param:  ?country=India&country=USA
    - Or comma-separate: ?country=India,USA
    Both formats work and are combined with OR logic (match any selected value).
    """
    result = await service.list_emails(
        params,
        country=country or None,
        state=state or None,
        domain=domain or None,
        university=university or None,
        uploaded_by=uploadedBy or None,
        used_by_employee=usedByEmployee or None,
        mail_source=mailSource or None,
        include_duplicates=includeDuplicates,
        search=search,
    )
    
    return ApiResponse(
        message="Emails fetched",
        data=result,
    )
