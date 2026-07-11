import uuid
from datetime import datetime, timezone

from app.core.exceptions import BadRequestException
from app.database.mongodb import get_collection
from app.email_master.model import build_email_master_document
from app.logs.model import LogAction, build_log_document
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.schemas.common import PaginationParams
from app.utils.csv_utils import parse_file_bytes, validate_and_clean_rows
from app.utils.pagination import build_paginated_response
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "email_master"


async def upload_file(
    employee_id: str,
    file_bytes: bytes,
    filename: str,
    insert_duplicates: bool = False,
    max_limit: int | None = None,
) -> dict:
    """
    Parse CSV/XLSX, deduplicate per-employee, insert into email_master.
    Email Master records are permanent and never deleted by campaign operations.
    
    Args:
        max_limit: Maximum number of emails to upload from file (1-10000)
    """
    master = get_collection(COLLECTION)

    try:
        df = parse_file_bytes(file_bytes, filename)
    except ValueError as exc:
        raise BadRequestException(str(exc)) from exc

    valid_rows, invalid_rows = validate_and_clean_rows(df)
    failed_count = len(invalid_rows)

    if not valid_rows:
        raise BadRequestException("No valid email rows found in the uploaded file")

    # Apply maxLimit if specified
    if max_limit:
        valid_rows = valid_rows[:max_limit]
        failed_count += len(invalid_rows) + (len(validate_and_clean_rows(df)[0]) - len(valid_rows))

    upload_batch = f"batch_{uuid.uuid4().hex[:12]}"
    batch_emails = [row["email"] for row in valid_rows]

    existing_cursor = master.find(
        {"employeeId": employee_id, "email": {"$in": batch_emails}},
        {"email": 1},
    )
    existing_emails = {doc["email"] async for doc in existing_cursor}

    docs_to_insert: list[dict] = []
    seen_in_batch: set[str] = set()
    unique_count = 0
    duplicate_count = 0
    duplicate_emails: list[dict] = []

    for row in valid_rows:
        email_addr = row["email"]
        is_dup = email_addr in existing_emails or email_addr in seen_in_batch
        if is_dup:
            duplicate_count += 1
            duplicate_emails.append(row)
            if not insert_duplicates:
                continue
        else:
            unique_count += 1
            seen_in_batch.add(email_addr)

        docs_to_insert.append(
            build_email_master_document(employee_id, upload_batch, is_dup, row)
        )

    if docs_to_insert:
        await master.insert_many(docs_to_insert)

    # Audit log
    logs = get_collection("logs")
    await logs.insert_one(
        build_log_document(
            employee_id=employee_id,
            profile_id=None,
            action=LogAction.UPLOAD,
            uploaded_count=len(valid_rows) + failed_count,
            unique_count=unique_count,
            duplicate_count=duplicate_count,
            sent_count=0,
            run_date=datetime.now(timezone.utc),
        )
    )

    total_uploaded = len(valid_rows) + failed_count
    limit_msg = f" (limited to {max_limit})" if max_limit else ""
    await create_notification(
        employee_id=employee_id,
        message=(
            f"Upload complete: {total_uploaded} records processed{limit_msg} "
            f"({unique_count} unique, {duplicate_count} duplicate, {failed_count} invalid)."
        ),
        type=NotificationType.SUCCESS if unique_count > 0 else NotificationType.WARNING,
    )

    return {
        "totalUploaded": total_uploaded,
        "unique": unique_count,
        "duplicate": duplicate_count,
        "failed": failed_count,
        "uploadBatch": upload_batch,
        "sample": serialize_list(docs_to_insert[:15]),
        "duplicateEmails": duplicate_emails[:15],
        "failedEmails": invalid_rows[:15],
    }


async def list_emails(
    employee_id: str | None,
    params: PaginationParams,
    country: str | None = None,
    domain: str | None = None,
    industry: str | None = None,
    company: str | None = None,
    include_duplicates: bool = True,
    search: str | None = None,
) -> dict:
    master = get_collection(COLLECTION)
    query: dict = {}

    if employee_id:
        query["employeeId"] = employee_id
    if country:
        query["country"] = country
    if domain:
        query["domain"] = domain
    if industry:
        query["industry"] = industry
    if company:
        query["company"] = {"$regex": company, "$options": "i"}
    if not include_duplicates:
        query["isDuplicate"] = False
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"fullName": {"$regex": search, "$options": "i"}},
            {"company": {"$regex": search, "$options": "i"}},
        ]

    total = await master.count_documents(query)
    cursor = (
        master.find(query)
        .sort("createdAt", -1)
        .skip(params.skip)
        .limit(params.pageSize)
    )
    docs = serialize_list([d async for d in cursor])
    return build_paginated_response(docs, total, params)


async def get_email(email_id: str) -> dict:
    master = get_collection(COLLECTION)
    doc = await master.find_one({"_id": to_object_id(email_id)})
    if not doc:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")
    return serialize_doc(doc)


async def get_dropdown_options(employee_id: str) -> dict:
    """Returns distinct filter values for the frontend dropdowns."""
    master = get_collection(COLLECTION)
    profiles_col = get_collection("profiles")

    domains = await master.distinct("domain", {"employeeId": employee_id})
    countries = await master.distinct("country", {"employeeId": employee_id})
    states = await master.distinct("state", {"employeeId": employee_id})
    industries = await master.distinct("industry", {"employeeId": employee_id})
    companies = await master.distinct("company", {"employeeId": employee_id})

    def clean(lst: list) -> list:
        return sorted([x for x in lst if x])

    cursor = profiles_col.find({"employeeId": employee_id}, {"profileName": 1})
    profiles_raw = serialize_list([p async for p in cursor])
    profiles_list = [
        {"id": p["id"], "name": p.get("profileName", "Unnamed Profile")}
        for p in profiles_raw
    ]

    return {
        "profiles": profiles_list,
        "domains": clean(domains),
        "countries": clean(countries),
        "states": clean(states),
        "industries": clean(industries),
        "companies": clean(companies),
    }


async def count_filtered_emails(employee_id: str, filters: dict) -> dict:
    """
    Count total emails matching the filter criteria.
    Returns both total count and count respecting filter configuration.
    """
    master = get_collection(COLLECTION)
    query: dict = {"employeeId": employee_id, "isDuplicate": False}

    if filters.get("country"):
        query["country"] = {"$in": filters["country"]}
    if filters.get("domain"):
        query["domain"] = {"$in": filters["domain"]}
    if filters.get("industry"):
        query["industry"] = {"$in": filters["industry"]}
    if filters.get("company"):
        query["company"] = {"$in": filters["company"]}
    if filters.get("type"):
        query["$or"] = [
            {"industry": {"$in": filters["type"]}},
            {"designation": {"$in": filters["type"]}},
        ]

    total_count = await master.count_documents(query)
    return {"totalMatching": total_count}


async def query_for_profile(
    employee_id: str,
    filters: dict,
    daily_limit: int,
    filter_limit: int = 0,
    exclude_profile_id: str | None = None,
) -> list[dict]:
    """
    Apply profile filters against email_master and return matching unique records.
    Used by the profile_emails generator — never modifies email_master.
    
    Args:
        employee_id: The employee's ID
        filters: Filter criteria (country, domain, industry, company, type)
        daily_limit: Daily limit for sends (used to determine pool size)
        filter_limit: Maximum emails to return from filtered results (0 = no limit)
        exclude_profile_id: Profile ID to exclude from results
    """
    master = get_collection(COLLECTION)
    query: dict = {"employeeId": employee_id, "isDuplicate": False}

    if filters.get("country"):
        query["country"] = {"$in": filters["country"]}
    if filters.get("domain"):
        query["domain"] = {"$in": filters["domain"]}
    if filters.get("industry"):
        query["industry"] = {"$in": filters["industry"]}
    if filters.get("company"):
        query["company"] = {"$in": filters["company"]}
    if filters.get("type"):
        query["$or"] = [
            {"industry": {"$in": filters["type"]}},
            {"designation": {"$in": filters["type"]}},
        ]

    # Determine fetch limit: use filter_limit if set, otherwise use daily_limit * 10
    fetch_limit = filter_limit if filter_limit > 0 else daily_limit * 10
    
    cursor = master.find(query).limit(fetch_limit)
    return serialize_list([d async for d in cursor])


async def mark_assigned_to_profile(master_ids: list[str], profile_id: str, employee_id: str) -> None:
    """Record that these email_master records were added to a profile's list."""
    from datetime import datetime, timezone
    master = get_collection(COLLECTION)
    from bson import ObjectId

    object_ids = [ObjectId(mid) for mid in master_ids if ObjectId.is_valid(mid)]
    now = datetime.now(timezone.utc)

    await master.update_many(
        {"_id": {"$in": object_ids}},
        {
            "$addToSet": {
                "assignedProfiles": {
                    "profileId": profile_id,
                    "employeeId": employee_id,
                    "assignedDate": now,
                }
            },
            "$set": {"updatedAt": now},
        },
    )
