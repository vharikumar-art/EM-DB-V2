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
    uploaded_by_id: str,
    uploaded_by_name: str,
    file_bytes: bytes,
    filename: str,
    insert_duplicates: bool = False,
    max_limit: int | None = None,
    mail_source: str | None = None,
) -> dict:
    """
    Parse CSV/XLSX, deduplicate GLOBALLY, insert into email_master.
    Email Master records are permanent and GLOBAL (all employees can see).
    
    Args:
        uploaded_by_id: User ID who uploaded
        uploaded_by_name: User name who uploaded
        max_limit: Maximum number of emails to upload from file (1-10000)
        mail_source: Source of emails - Google Scholar, University, Other (overrides CSV value)
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

    # GLOBAL deduplication: check entire collection
    existing_cursor = master.find(
        {"email": {"$in": batch_emails}},
        {"email": 1, "_id": 1},
    )
    existing_emails = {doc["email"]: str(doc["_id"]) async for doc in existing_cursor}

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

        # If a mail_source was provided during upload UI, override the CSV value for every row
        if mail_source:
            row["mailSource"] = mail_source

        docs_to_insert.append(
            build_email_master_document(
                upload_batch=upload_batch,
                is_duplicate=is_dup,
                uploaded_by=uploaded_by_id,
                uploaded_by_name=uploaded_by_name,
                row=row,
            )
        )

    if docs_to_insert:
        await master.insert_many(docs_to_insert)

    # Audit log
    logs = get_collection("logs")
    await logs.insert_one(
        build_log_document(
            employee_id=uploaded_by_id,
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
        employee_id=uploaded_by_id,
        message=(
            f"Email upload complete: {total_uploaded} records processed{limit_msg} "
            f"({unique_count} new, {duplicate_count} duplicate, {failed_count} invalid)."
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
    params: PaginationParams,
    country: str | None = None,
    domain: str | None = None,
    industry: str | None = None,
    company: str | None = None,
    uploaded_by: str | None = None,
    used_by_employee: str | None = None,
    mail_source: str | None = None,
    include_duplicates: bool = True,
    search: str | None = None,
) -> dict:
    """List emails from GLOBAL pool with optional filters."""
    master = get_collection(COLLECTION)
    query: dict = {}

    if country:
        query["country"] = country
    if domain:
        query["domain"] = domain
    if industry:
        query["industry"] = industry
    if company:
        query["company"] = {"$regex": company, "$options": "i"}
    if uploaded_by:
        query["uploadedBy"] = uploaded_by
    if used_by_employee:
        query["usedByEmployeeId"] = used_by_employee
    if mail_source:
        query["mailSource"] = mail_source
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
        .sort("uploadedDate", -1)
        .skip(params.skip)
        .limit(params.pageSize)
    )
    docs = serialize_list([d async for d in cursor])
    
    # Enrich with employee names
    docs = await _enrich_emails_with_employee_names(docs)
    
    return build_paginated_response(docs, total, params)


async def _enrich_emails_with_employee_names(docs: list[dict]) -> list[dict]:
    """Populate employee names from usedInProfiles or usedByEmployeeId.
    
    The employeeId stored can be either:
    - employees._id  (assigned after profile email generation)
    - users._id      (assigned directly in older records)
    We try both to resolve the name.
    """
    if not docs:
        return docs
    
    from bson import ObjectId
    users_col = get_collection("users")
    employees_col = get_collection("employees")
    
    # Cache for resolved names (keyed by raw id string)
    name_cache: dict[str, str] = {}
    
    async def resolve_name(id_str: str) -> str:
        """Try employees._id first, then users._id directly."""
        if id_str in name_cache:
            return name_cache[id_str]
        
        if not ObjectId.is_valid(id_str):
            name_cache[id_str] = id_str
            return id_str
        
        emp_name = None
        
        # 1) Try as employees._id → get linked user name
        try:
            emp_doc = await employees_col.find_one({"_id": ObjectId(id_str)})
            if emp_doc and emp_doc.get("userId"):
                user_doc = await users_col.find_one({"_id": ObjectId(emp_doc["userId"])})
                if user_doc:
                    emp_name = user_doc.get("name")
        except Exception:
            pass
        
        # 2) Try as users._id directly
        if not emp_name:
            try:
                user_doc = await users_col.find_one({"_id": ObjectId(id_str)})
                if user_doc:
                    emp_name = user_doc.get("name")
            except Exception:
                pass
        
        # 3) Fall back to raw ID
        result = emp_name or id_str
        name_cache[id_str] = result
        return result
    
    for doc in docs:
        id_str = doc.get("usedByEmployeeId")
        if not id_str:
            used_profiles = doc.get("usedInProfiles", [])
            if used_profiles:
                id_str = used_profiles[0].get("employeeId")
        
        if id_str:
            id_str = str(id_str)
            resolved = await resolve_name(id_str)
            doc["usedByEmployeeName"] = resolved
            doc["usedByEmployeeId"] = id_str
            doc["inProfileEmails"] = True
    
    return docs



async def get_email(email_id: str) -> dict:
    master = get_collection(COLLECTION)
    doc = await master.find_one({"_id": to_object_id(email_id)})
    if not doc:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")
    
    doc = serialize_doc(doc)
    
    # Enrich with employee name
    docs = await _enrich_emails_with_employee_names([doc])
    return docs[0] if docs else doc


async def delete_email(email_id: str) -> None:
    """ADMIN ONLY: Delete email from global pool."""
    master = get_collection(COLLECTION)
    result = await master.delete_one({"_id": to_object_id(email_id)})
    if result.deleted_count == 0:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")


async def get_dropdown_options() -> dict:
    """Returns distinct filter values for the GLOBAL email pool."""
    master = get_collection(COLLECTION)
    employees_col = get_collection("employees")
    users_col = get_collection("users")

    domains = await master.distinct("domain", {"isDuplicate": False})
    countries = await master.distinct("country", {"isDuplicate": False})
    states = await master.distinct("state", {"isDuplicate": False})
    industries = await master.distinct("industry", {"isDuplicate": False})
    companies = await master.distinct("company", {"isDuplicate": False})
    mail_sources = await master.distinct("mailSource", {"isDuplicate": False})
    
    # Get all uploaders with their names
    uploaders_data = {}
    cursor = master.find({}, {"uploadedBy": 1, "uploadedByName": 1})
    async for doc in cursor:
        uid = doc.get("uploadedBy")
        uname = doc.get("uploadedByName") or uid
        if uid and uid not in uploaders_data:
            uploaders_data[uid] = uname

    # Get all employees who have used emails
    used_by_employees_data = {}
    
    # From usedInProfiles
    cursor = master.find(
        {"usedInProfiles": {"$exists": True, "$ne": []}},
        {"usedInProfiles": 1}
    )
    async for doc in cursor:
        used_profiles = doc.get("usedInProfiles", [])
        for profile in used_profiles:
            emp_id = profile.get("employeeId")
            if emp_id and emp_id not in used_by_employees_data:
                # Try to get employee name
                try:
                    employee = await employees_col.find_one({"_id": emp_id})
                    if employee:
                        user_id = employee.get("userId")
                        if user_id:
                            user = await users_col.find_one({"_id": user_id})
                            if user:
                                emp_name = user.get("name", emp_id)
                                used_by_employees_data[emp_id] = emp_name
                                continue
                except Exception:
                    pass
                # Fallback to ID
                used_by_employees_data[emp_id] = emp_id
    
    # From usedByEmployeeId field
    cursor = master.find(
        {"usedByEmployeeId": {"$exists": True, "$ne": None}},
        {"usedByEmployeeId": 1, "usedByEmployeeName": 1}
    )
    async for doc in cursor:
        emp_id = doc.get("usedByEmployeeId")
        emp_name = doc.get("usedByEmployeeName")
        
        if emp_id:
            if emp_name and emp_id not in used_by_employees_data:
                used_by_employees_data[emp_id] = emp_name
            elif emp_id not in used_by_employees_data:
                # Try to fetch
                try:
                    employee = await employees_col.find_one({"_id": emp_id})
                    if employee:
                        user_id = employee.get("userId")
                        if user_id:
                            user = await users_col.find_one({"_id": user_id})
                            if user:
                                emp_name = user.get("name", emp_id)
                                used_by_employees_data[emp_id] = emp_name
                                continue
                except Exception:
                    pass
                used_by_employees_data[emp_id] = emp_id

    def clean(lst: list) -> list:
        return sorted([x for x in lst if x])

    uploaders = [{"id": uid, "name": uname} for uid, uname in uploaders_data.items()] if uploaders_data else []
    used_by_employees = [{"id": eid, "name": ename} for eid, ename in used_by_employees_data.items()] if used_by_employees_data else []

    return {
        "domains": clean(domains),
        "countries": clean(countries),
        "states": clean(states),
        "industries": clean(industries),
        "companies": clean(companies),
        "mailSources": clean(mail_sources),
        "uploaders": uploaders,
        "usedByEmployees": used_by_employees,
    }


async def get_uploader_stats() -> dict:
    """Get upload contribution statistics by user."""
    master = get_collection(COLLECTION)
    
    try:
        pipeline = [
            {
                "$group": {
                    "_id": {"uploadedBy": "$uploadedBy", "uploadedByName": "$uploadedByName"},
                    "totalEmails": {"$sum": 1},
                    "uniqueEmails": {"$sum": {"$cond": [{"$eq": ["$isDuplicate", False]}, 1, 0]}},
                    "duplicateEmails": {"$sum": {"$cond": [{"$eq": ["$isDuplicate", True]}, 1, 0]}},
                    "lastUploadDate": {"$max": "$uploadedDate"},
                }
            },
            {"$sort": {"totalEmails": -1}},
        ]
        
        results = await master.aggregate(pipeline).to_list(None)
        return {
            "stats": [
                {
                    "uploadedBy": r["_id"]["uploadedBy"],
                    "uploadedByName": r["_id"]["uploadedByName"] or r["_id"]["uploadedBy"],
                    "totalEmails": r["totalEmails"],
                    "uniqueEmails": r["uniqueEmails"],
                    "duplicateEmails": r["duplicateEmails"],
                    "lastUploadDate": r["lastUploadDate"],
                }
                for r in results
            ]
        }
    except Exception as exc:
        import logging
        logging.error(f"Error getting uploader stats: {exc}")
        return {"stats": []}


async def count_filtered_emails(filters: dict) -> dict:
    """
    Count total emails matching the filter criteria from GLOBAL pool.
    Returns both total count and count respecting filter configuration.
    """
    master = get_collection(COLLECTION)
    query: dict = {"isDuplicate": False}

    if filters.get("country"):
        query["country"] = {"$in": filters["country"]}
    if filters.get("domain"):
        query["domain"] = {"$in": filters["domain"]}
    if filters.get("industry"):
        query["industry"] = {"$in": filters["industry"]}
    if filters.get("company"):
        query["company"] = {"$in": filters["company"]}
    if filters.get("mailSource"):
        query["mailSource"] = {"$in": filters["mailSource"]}
    if filters.get("type"):
        query["$or"] = [
            {"industry": {"$in": filters["type"]}},
            {"designation": {"$in": filters["type"]}},
        ]

    total_count = await master.count_documents(query)
    return {"totalMatching": total_count}


async def query_for_profile(
    filters: dict,
    daily_limit: int,
    filter_limit: int = 0,
    employee_id: str | None = None,
) -> list[dict]:
    """
    Apply profile filters against GLOBAL email_master and return matching unique records.
    Skips emails already assigned to OTHER employees (doesn't count them against filter_limit).
    
    Args:
        filters: Filter criteria (country, domain, industry, company, type)
        daily_limit: Daily limit for sends (used to determine pool size)
        filter_limit: Maximum emails to return from filtered results (0 = no limit)
        employee_id: Current employee ID (to track who claims emails)
    """
    master = get_collection(COLLECTION)
    query: dict = {"isDuplicate": False}

    # Track if user provided explicit filters
    has_explicit_filters = any([
        filters.get("country"),
        filters.get("domain"),
        filters.get("industry"),
        filters.get("company"),
        filters.get("type"),
        filters.get("mailSource"),
    ])

    if filters.get("country"):
        query["country"] = {"$in": filters["country"]}
    if filters.get("domain"):
        query["domain"] = {"$in": filters["domain"]}
    if filters.get("industry"):
        query["industry"] = {"$in": filters["industry"]}
    if filters.get("company"):
        query["company"] = {"$in": filters["company"]}
    if filters.get("mailSource"):
        query["mailSource"] = {"$in": filters["mailSource"]}
    if filters.get("type"):
        query["$or"] = [
            {"industry": {"$in": filters["type"]}},
            {"designation": {"$in": filters["type"]}},
        ]

    # Determine fetch limit: use filter_limit if set, otherwise use daily_limit * 10
    fetch_limit = filter_limit if filter_limit > 0 else daily_limit * 10
    
    # Fetch all matching records (including already-assigned)
    cursor = master.find(query).limit(fetch_limit * 2)  # Fetch extra to account for skipped
    all_results = serialize_list([d async for d in cursor])
    
    # Filter in application code: skip emails assigned to OTHER employees
    available_results = []
    for email_record in all_results:
        used_by_id = email_record.get("usedByEmployeeId")
        
        # Include if:
        # 1. Not assigned to anyone (used_by_id is None)
        # 2. Assigned to current employee (can use own assignments)
        if used_by_id is None or used_by_id == employee_id:
            available_results.append(email_record)
        # SKIP if assigned to different employee (don't count against limit)
    
    # Return only the requested limit
    return available_results[:fetch_limit]


async def mark_used_in_profile(master_ids: list[str], profile_id: str, employee_id: str) -> None:
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
                "usedInProfiles": {
                    "profileId": profile_id,
                    "employeeId": employee_id,
                    "usedDate": now,
                }
            },
            "$set": {"updatedAt": now},
        },
    )


async def mark_emails_assigned_to_employee(
    master_ids: list[str], 
    employee_id: str, 
    employee_name: str
) -> None:
    """Mark emails as assigned to a specific employee (claim them)."""
    from datetime import datetime, timezone
    master = get_collection(COLLECTION)
    from bson import ObjectId

    object_ids = [ObjectId(mid) for mid in master_ids if ObjectId.is_valid(mid)]
    now = datetime.now(timezone.utc)

    await master.update_many(
        {"_id": {"$in": object_ids}},
        {
            "$set": {
                "inProfileEmails": True,
                "usedByEmployeeId": employee_id,
                "usedByEmployeeName": employee_name,
                "assignedDate": now,
                "updatedAt": now,
            }
        },
    )


async def clear_all_emails() -> dict:
    """ADMIN ONLY: Delete ALL emails from email_master collection. WARNING: Irreversible!"""
    master = get_collection(COLLECTION)
    
    # Get count before deletion
    total_count = await master.count_documents({})
    
    # Delete all documents
    result = await master.delete_many({})
    
    return {
        "message": "Email master table cleared",
        "deletedCount": result.deleted_count,
        "previousTotal": total_count,
    }
