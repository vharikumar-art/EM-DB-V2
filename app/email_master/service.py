import uuid
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.core.exceptions import BadRequestException, ForbiddenException
from app.database.mongodb import get_collection
from app.email_master.model import build_email_master_document
from app.settings.service import get_integer_setting
from app.logs.model import LogAction, build_log_document
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.schemas.common import PaginationParams
from app.utils.csv_utils import parse_file_bytes, validate_and_clean_rows
from app.utils.pagination import build_paginated_response
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "email_master"

# ── In-memory cache for dropdown options ─────────────────────────────────────
# These values rarely change (only when a new CSV is uploaded), so we cache
# the result for 30 minutes to avoid full-collection scans on every page load.
_DROPDOWN_CACHE: dict | None = None
_DROPDOWN_CACHE_AT: datetime | None = None
_DROPDOWN_CACHE_TTL_SECONDS = 30 * 60  # 30 minutes


def invalidate_dropdown_cache() -> None:
    """Call this after a new upload so the cache refreshes on next request."""
    global _DROPDOWN_CACHE, _DROPDOWN_CACHE_AT
    _DROPDOWN_CACHE = None
    _DROPDOWN_CACHE_AT = None


def _filter_values(value: Any) -> list[str]:
    """Normalize one filter value or a comma-separated value into a list."""
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    return [
        item.strip()
        for value_item in values
        for item in str(value_item).split(",")
        if item.strip()
    ]


async def upload_file(
    uploaded_by_id: str,
    uploaded_by_name: str,
    file_bytes: bytes,
    filename: str,
    insert_duplicates: bool = False,
    mail_source: str | None = None,
) -> dict:
    """
    Parse CSV/XLSX, deduplicate GLOBALLY, insert into email_master.
    Email Master records are permanent and GLOBAL (all employees can see).
    
    Args:
        uploaded_by_id: User ID who uploaded
        uploaded_by_name: User name who uploaded
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

    for row in valid_rows:
        email_addr = row["email"]
        is_dup = email_addr in existing_emails or email_addr in seen_in_batch
        if is_dup:
            duplicate_count += 1
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
    await create_notification(
        employee_id=uploaded_by_id,
        message=(
            f"Email upload complete: {total_uploaded} records processed "
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
        "failedEmails": invalid_rows,
    }



async def list_emails(
    params: PaginationParams,
    country: list[str] | str | None = None,
    state: list[str] | str | None = None,
    domain: list[str] | str | None = None,
    university: list[str] | str | None = None,
    uploaded_by: list[str] | str | None = None,
    used_by_employee: list[str] | str | None = None,
    mail_source: list[str] | str | None = None,
    include_duplicates: bool = True,
    search: str | None = None,
) -> dict:
    """List emails from GLOBAL pool with optional filters.
    
    All filter params support multi-value lists — values are combined with OR logic.
    Comma-separated strings (e.g. 'India,USA') are also accepted and split automatically.
    """
    master = get_collection(COLLECTION)
    query: dict = {}
    and_clauses: list[dict] = []

    # Helper: normalise a raw filter value (str, list[str], or None)
    # into a clean de-duplicated list, splitting on commas.
    def _vals(v) -> list[str]:
        return _filter_values(v)

    # ── country ──────────────────────────────────────────────────────────────
    countries = _vals(country)
    if countries:
        query["country"] = {"$in": countries} if len(countries) > 1 else countries[0]

    # ── state ────────────────────────────────────────────────────────────────
    states = _vals(state)
    if states:
        query["state"] = {"$in": states} if len(states) > 1 else states[0]

    # ── domain / domain_group (searches both fields) ──────────────────────────
    domains = _vals(domain)
    if domains:
        if len(domains) == 1:
            and_clauses.append({"$or": [
                {"domain": domains[0]},
                {"domain_group": domains[0]},
            ]})
        else:
            and_clauses.append({"$or": [
                {"domain": {"$in": domains}},
                {"domain_group": {"$in": domains}},
            ]})

    # ── university (partial match, multi-value → OR of regex) ─────────────────
    universities = _vals(university)
    if universities:
        if len(universities) == 1:
            query["university"] = {"$regex": universities[0], "$options": "i"}
        else:
            and_clauses.append({"$or": [
                {"university": {"$regex": u, "$options": "i"}}
                for u in universities
            ]})

    # ── uploadedBy ────────────────────────────────────────────────────────────
    uploaders = _vals(uploaded_by)
    if uploaders:
        query["uploadedBy"] = {"$in": uploaders} if len(uploaders) > 1 else uploaders[0]

    # ── usedByEmployee ────────────────────────────────────────────────────────
    used_emps = _vals(used_by_employee)
    if used_emps:
        and_clauses.append({"$or": [
            {"usedByEmployeeId": {"$in": used_emps}},
            {"usedByEmployeeIds": {"$in": used_emps}},
        ]})

    # ── mailSource ────────────────────────────────────────────────────────────
    mail_sources = _vals(mail_source)
    if mail_sources:
        query["mailSource"] = {"$in": mail_sources} if len(mail_sources) > 1 else mail_sources[0]

    # ── includeDuplicates ─────────────────────────────────────────────────────
    if not include_duplicates:
        query["isDuplicate"] = False

    # ── search (full-text across key fields) ──────────────────────────────────
    if search:
        and_clauses.append({"$or": [
            {"email": {"$regex": search, "$options": "i"}},
            {"fullName": {"$regex": search, "$options": "i"}},
            {"university": {"$regex": search, "$options": "i"}},
            {"domain": {"$regex": search, "$options": "i"}},
            {"domain_group": {"$regex": search, "$options": "i"}},
            {"country": {"$regex": search, "$options": "i"}},
        ]})

    if and_clauses:
        query["$and"] = and_clauses

    # Use fast estimated count when there are no filters applied
    if query:
        total = await master.count_documents(query)
    else:
        total = await master.estimated_document_count()

    cursor = (
        master.find(query)
        .sort("uploadedDate", -1)
        .skip(params.skip)
        .limit(params.pageSize)
    )
    docs = serialize_list([d async for d in cursor])
    
    # Enrich with employee names (batch lookups — no N+1)
    docs = await _enrich_emails_with_employee_names(docs)
    
    return build_paginated_response(docs, total, params)


async def _enrich_emails_with_employee_names(docs: list[dict]) -> list[dict]:
    """Populate employee names from usedInProfiles or usedByEmployeeId.

    Uses batched DB lookups (2 queries total) instead of N+1 individual queries.
    """
    if not docs:
        return docs

    from bson import ObjectId
    users_col = get_collection("users")
    employees_col = get_collection("employees")

    # ── Step 1: Collect all unique employee/user IDs across the page ──────────
    all_ids: set[str] = set()
    for doc in docs:
        if old_id := doc.get("usedByEmployeeId"):
            all_ids.add(str(old_id))
        for up in doc.get("usedInProfiles", []):
            if uid := up.get("employeeId"):
                all_ids.add(str(uid))
        for eid in doc.get("usedByEmployeeIds", []):
            all_ids.add(str(eid))

    valid_object_ids = [ObjectId(i) for i in all_ids if ObjectId.is_valid(i)]

    # ── Step 2: Batch-fetch employees and users in exactly 2 queries ──────────
    name_cache: dict[str, str] = {}

    if valid_object_ids:
        # employees._id → userId mapping
        emp_to_user: dict[str, str] = {}
        async for emp in employees_col.find(
            {"_id": {"$in": valid_object_ids}}, {"_id": 1, "userId": 1}
        ):
            emp_to_user[str(emp["_id"])] = str(emp["userId"]) if emp.get("userId") else ""

        # Gather all user IDs we need to resolve (direct IDs + linked from employees)
        all_user_ids = [
            ObjectId(uid)
            for uid in {*[v for v in emp_to_user.values() if v], *all_ids}
            if ObjectId.is_valid(uid)
        ]
        user_names: dict[str, str] = {}
        async for user in users_col.find(
            {"_id": {"$in": all_user_ids}}, {"_id": 1, "name": 1}
        ):
            user_names[str(user["_id"])] = user.get("name") or ""

        # Build the final cache: raw id → display name
        for raw_id in all_ids:
            if not ObjectId.is_valid(raw_id):
                name_cache[raw_id] = raw_id
                continue
            # Try as employee ID first
            linked_user_id = emp_to_user.get(raw_id)
            name = (user_names.get(linked_user_id) if linked_user_id else None) \
                or user_names.get(raw_id) \
                or raw_id
            name_cache[raw_id] = name

    # ── Step 3: Annotate docs using the cache (no more DB calls) ─────────────
    for doc in docs:
        if "usedByEmployeeIds" not in doc:
            doc["usedByEmployeeIds"] = []
        if "usedByEmployeeNames" not in doc:
            doc["usedByEmployeeNames"] = []

        old_id = doc.get("usedByEmployeeId")
        old_name = doc.get("usedByEmployeeName")

        if not doc["usedByEmployeeIds"] and old_id:
            id_str = str(old_id)
            doc["usedByEmployeeIds"].append(id_str)
            doc["usedByEmployeeNames"].append(
                old_name or name_cache.get(id_str, id_str)
            )

        if not doc["usedByEmployeeIds"]:
            for up in doc.get("usedInProfiles", []):
                uid = up.get("employeeId")
                if uid and str(uid) not in doc["usedByEmployeeIds"]:
                    id_str = str(uid)
                    doc["usedByEmployeeIds"].append(id_str)
                    doc["usedByEmployeeNames"].append(name_cache.get(id_str, id_str))

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


async def mark_email_reply(
    email: str,
    reason: str,
    custom_reason: str | None,
    marked_by: str,
    marked_by_name: str | None = None,
) -> dict:
    """Mark an address as replied and remove it from active profile email lists."""
    master = get_collection(COLLECTION)
    normalized_email = email.strip().lower()
    now = datetime.now(timezone.utc)
    update = {
        "hasReply": True,
        "replyReason": reason,
        "replyCustomReason": custom_reason if reason == "other" else None,
        "replyMarkedAt": now,
        "replyMarkedBy": marked_by,
        "replyMarkedByName": marked_by_name or marked_by,
        "updatedAt": now,
    }
    result = await master.update_many(
        {"email": {"$regex": f"^{normalized_email}$", "$options": "i"}},
        {"$set": update},
    )
    if result.matched_count == 0:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")

    matched_cursor = master.find(
        {"email": {"$regex": f"^{normalized_email}$", "$options": "i"}},
        {"_id": 1},
    )
    master_ids = [doc["_id"] async for doc in matched_cursor]
    profile_emails = get_collection("profile_emails")
    if master_ids:
        await profile_emails.delete_many({"masterEmailId": {"$in": [str(mid) for mid in master_ids]}})
        await master.update_many(
            {"_id": {"$in": master_ids}},
            {
                "$pull": {"usedInProfiles": {"profileId": {"$exists": True}}},
                "$set": {"inProfileEmails": False, "updatedAt": now},
            },
        )

    doc = await master.find_one(
        {"email": {"$regex": f"^{normalized_email}$", "$options": "i"}},
        sort=[("replyMarkedAt", -1)],
    )
    return serialize_doc(doc)


async def get_user_display_name(user_id: str) -> str:
    """Return a user's display name when given either a user or employee ID."""
    from bson import ObjectId

    users = get_collection("users")
    employees = get_collection("employees")
    object_id = ObjectId(user_id) if ObjectId.is_valid(user_id) else None
    user_queries = [{"_id": object_id or user_id}, {"id": user_id}]
    user = None
    for query in user_queries:
        user = await users.find_one(query, {"name": 1, "email": 1})
        if user:
            break
    if user:
        return user.get("name") or user.get("email") or user_id

    employee_queries = [{"userId": user_id}]
    if object_id:
        employee_queries.extend([{"userId": object_id}, {"_id": object_id}])
    employee = None
    for query in employee_queries:
        employee = await employees.find_one(query, {"userId": 1})
        if employee:
            break
    employee_user_id = (employee or {}).get("userId")
    if employee_user_id:
        employee_user_query = (
            {"_id": ObjectId(str(employee_user_id))}
            if ObjectId.is_valid(str(employee_user_id))
            else {"_id": employee_user_id}
        )
        user = await users.find_one(employee_user_query, {"name": 1, "email": 1})

    return (user or {}).get("name") or (user or {}).get("email") or user_id


async def _get_reply_marker_scope(user_id: str, role: str) -> set[str] | None:
    """Return marker IDs visible to a user, or None for an unrestricted user."""
    if role == "super_admin":
        return None

    employees = get_collection("employees")
    scope: set[str] = {str(user_id)}
    own_employee = await employees.find_one({"userId": user_id}, {"_id": 1})
    if not own_employee:
        from bson import ObjectId

        if ObjectId.is_valid(user_id):
            own_employee = await employees.find_one(
                {"userId": ObjectId(user_id)}, {"_id": 1}
            )

    own_employee_id = str(own_employee["_id"]) if own_employee else None
    if own_employee_id:
        scope.add(own_employee_id)

    if role != "admin" or not own_employee_id:
        return scope

    assigned_queries = [{"assignedToAdmin": own_employee_id}]
    from bson import ObjectId

    if ObjectId.is_valid(own_employee_id):
        assigned_queries.append({"assignedToAdmin": ObjectId(own_employee_id)})
    seen_employee_ids: set[str] = set()
    for assigned_query in assigned_queries:
        assigned = employees.find(assigned_query, {"_id": 1, "userId": 1})
        async for employee in assigned:
            employee_id = str(employee["_id"])
            if employee_id in seen_employee_ids:
                continue
            seen_employee_ids.add(employee_id)
            scope.add(employee_id)
            if employee.get("userId"):
                scope.add(str(employee["userId"]))

    return scope


def _reply_updated_range(
    updated_time: str | None,
    updated_start_date: date | None,
    updated_end_date: date | None,
) -> tuple[datetime, datetime] | None:
    if not updated_time:
        if updated_start_date or updated_end_date:
            if not updated_start_date or not updated_end_date:
                raise BadRequestException(
                    "updatedStartDate and updatedEndDate are both required"
                )
            if updated_start_date > updated_end_date:
                raise BadRequestException("updatedStartDate must be before updatedEndDate")
            return (
                datetime.combine(updated_start_date, time.min, tzinfo=timezone.utc),
                datetime.combine(updated_end_date, time.max, tzinfo=timezone.utc),
            )
        return None

    if updated_time == "custom":
        return _reply_updated_range(None, updated_start_date, updated_end_date)
    if updated_time not in {"last_7_days", "last_15_days", "last_30_days"}:
        raise BadRequestException(
            "updatedTime must be last_7_days, last_15_days, last_30_days, or custom"
        )

    days = int(updated_time.split("_")[1])
    now = datetime.now(timezone.utc)
    return now - timedelta(days=days), now


async def get_reply_filter_options(
    user_id: str | None = None,
    role: str | None = None,
) -> dict:
    """Return filter values available to the current user's reply scope."""
    master = get_collection(COLLECTION)
    query: dict = {"hasReply": True}
    if user_id and role:
        marker_scope = await _get_reply_marker_scope(user_id, role)
        if marker_scope is not None:
            query["replyMarkedBy"] = {"$in": list(marker_scope)}

    reasons: set[str] = set()
    marker_names: set[str] = set()
    async for doc in master.find(
        query, {"replyReason": 1, "replyMarkedBy": 1, "replyMarkedByName": 1}
    ):
        if doc.get("replyReason"):
            reasons.add(doc["replyReason"])
        marker_id = str(doc.get("replyMarkedBy")) if doc.get("replyMarkedBy") else None
        marker_name = doc.get("replyMarkedByName")
        if marker_id and (not marker_name or str(marker_name) == marker_id):
            marker_name = await get_user_display_name(marker_id)
        if marker_name and marker_name != marker_id:
            marker_names.add(str(marker_name))

    reason_labels = {
        "replied": "Replied",
        "converted": "Converted",
        "other": "Other",
    }
    return {
        "reasons": [
            {"value": reason, "label": reason_labels.get(reason, reason)}
            for reason in sorted(reasons)
        ],
        "replyMarkedByNames": [
            {"value": name, "label": name} for name in sorted(marker_names, key=str.casefold)
        ],
        "updatedTimePresets": [
            {"value": "last_7_days", "label": "Last 7 days"},
            {"value": "last_15_days", "label": "Last 15 days"},
            {"value": "last_30_days", "label": "Last 30 days"},
            {"value": "custom", "label": "Custom date range"},
        ],
    }


async def list_email_replies(
    params: PaginationParams,
    search: str | None = None,
    user_id: str | None = None,
    role: str | None = None,
    reason: str | None = None,
    reply_marked_by_name: str | None = None,
    updated_time: str | None = None,
    updated_start_date: date | None = None,
    updated_end_date: date | None = None,
) -> dict:
    """List email-master records marked as having received a reply."""
    updated_range = _reply_updated_range(
        updated_time, updated_start_date, updated_end_date
    )
    master = get_collection(COLLECTION)
    query: dict = {"hasReply": True}
    marker_scope: set[str] | None = None
    if user_id and role:
        marker_scope = await _get_reply_marker_scope(user_id, role)
        if marker_scope is not None:
            query["replyMarkedBy"] = {"$in": list(marker_scope)}
    if reason:
        query["replyReason"] = reason
    if reply_marked_by_name:
        name_conditions = [
            {
                "replyMarkedByName": {
                    "$regex": f"^{re.escape(reply_marked_by_name)}$",
                    "$options": "i",
                }
            }
        ]
        marker_query: dict = {"hasReply": True}
        if marker_scope is not None:
            marker_query["replyMarkedBy"] = {"$in": list(marker_scope)}
        matching_marker_ids: set[str] = set()
        async for marker_doc in master.find(
            marker_query, {"replyMarkedBy": 1, "replyMarkedByName": 1}
        ):
            marker_id = marker_doc.get("replyMarkedBy")
            if not marker_id:
                continue
            stored_name = marker_doc.get("replyMarkedByName")
            resolved_name = stored_name
            if not stored_name or str(stored_name) == str(marker_id):
                resolved_name = await get_user_display_name(str(marker_id))
            if resolved_name and str(resolved_name).casefold() == reply_marked_by_name.casefold():
                matching_marker_ids.add(str(marker_id))
        if matching_marker_ids:
            name_conditions.append({"replyMarkedBy": {"$in": list(matching_marker_ids)}})
        query.setdefault("$and", []).append({"$or": name_conditions})
    if updated_range:
        query["updatedAt"] = {"$gte": updated_range[0], "$lte": updated_range[1]}
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"fullName": {"$regex": search, "$options": "i"}},
        ]

    total = await master.count_documents(query)
    converted_query = {**query, "replyReason": "converted"}
    other_query = {**query, "replyReason": "other"}
    converted_count = await master.count_documents(converted_query)
    other_count = await master.count_documents(other_query)
    cursor = (
        master.find(query)
        .sort("replyMarkedAt", -1)
        .skip(params.skip)
        .limit(params.pageSize)
    )
    docs = serialize_list([doc async for doc in cursor])
    for doc in docs:
        marked_by = doc.get("replyMarkedBy")
        marked_by_name = doc.get("replyMarkedByName")
        if marked_by and (not marked_by_name or str(marked_by_name) == str(marked_by)):
            doc["replyMarkedByName"] = await get_user_display_name(str(marked_by))

    response = build_paginated_response(docs, total, params).model_dump()
    response.update(
        {
            "replyCount": total,
            "convertedCount": converted_count,
            "otherCount": other_count,
        }
    )
    return response


async def update_email_reply(
    email_id: str,
    payload: dict,
    marked_by: str,
    role: str | None = None,
) -> dict:
    """Edit or clear reply tracking for one email-master record."""
    master = get_collection(COLLECTION)
    object_id = to_object_id(email_id)
    doc = await master.find_one({"_id": object_id})
    if not doc:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")

    if role:
        marker_scope = await _get_reply_marker_scope(marked_by, role)
        if marker_scope is not None and str(doc.get("replyMarkedBy")) not in marker_scope:
            raise ForbiddenException("You do not have access to this email reply")

    has_reply = payload.get("hasReply", doc.get("hasReply", False))
    reason = payload.get("reason", doc.get("replyReason"))
    custom_reason = payload.get("customReason", doc.get("replyCustomReason"))
    if has_reply and reason == "other" and not custom_reason:
        raise BadRequestException("customReason is required when reason is 'other'")
    if has_reply and not reason:
        raise BadRequestException("reason is required when hasReply is true")

    now = datetime.now(timezone.utc)
    marked_by_name = await get_user_display_name(marked_by)
    update = {
        "hasReply": has_reply,
        "replyReason": reason if has_reply else None,
        "replyCustomReason": custom_reason if has_reply and reason == "other" else None,
        "replyMarkedAt": now if has_reply else None,
        "replyMarkedBy": marked_by if has_reply else None,
        "replyMarkedByName": marked_by_name if has_reply else None,
        "updatedAt": now,
    }
    updated = await master.find_one_and_update(
        {"_id": object_id},
        {"$set": update},
        return_document=True,
    )
    return serialize_doc(updated)


async def delete_email(email_id: str) -> None:
    """ADMIN ONLY: Delete email from global pool."""
    master = get_collection(COLLECTION)
    result = await master.delete_one({"_id": to_object_id(email_id)})
    if result.deleted_count == 0:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")


async def get_dropdown_options() -> dict:
    """Returns distinct filter values for the GLOBAL email pool.

    Results are cached in-memory for 30 minutes to avoid repeated full-collection
    scans on a potentially large email_master table.
    """
    global _DROPDOWN_CACHE, _DROPDOWN_CACHE_AT

    # ── Serve from cache if still fresh ──────────────────────────────────────
    now = datetime.now(timezone.utc)
    if _DROPDOWN_CACHE is not None and _DROPDOWN_CACHE_AT is not None:
        age = (now - _DROPDOWN_CACHE_AT).total_seconds()
        if age < _DROPDOWN_CACHE_TTL_SECONDS:
            return _DROPDOWN_CACHE

    from bson import ObjectId
    master = get_collection(COLLECTION)
    employees_col = get_collection("employees")
    users_col = get_collection("users")

    # ── Run all distinct() queries concurrently ───────────────────────────────
    import asyncio
    no_dup = {"isDuplicate": False}
    (
        domains,
        domain_groups,
        countries,
        states,
        universities,
        designations,
        mail_sources,
    ) = await asyncio.gather(
        master.distinct("domain", no_dup),
        master.distinct("domain_group", no_dup),
        master.distinct("country", no_dup),
        master.distinct("state", no_dup),
        master.distinct("university", no_dup),
        master.distinct("designation", no_dup),
        master.distinct("mailSource", no_dup),
    )

    # ── Collect uploaders (stored directly on the document) ───────────────────
    uploaders_data: dict[str, str] = {}
    async for doc in master.find(
        {"uploadedBy": {"$exists": True, "$ne": None}},
        {"uploadedBy": 1, "uploadedByName": 1},
    ):
        uid = doc.get("uploadedBy")
        uname = doc.get("uploadedByName") or uid
        if uid and uid not in uploaders_data:
            uploaders_data[uid] = uname

    # ── Collect all unique employee IDs that have used emails ─────────────────
    raw_used_emp: dict[str, str | None] = {}  # id → stored name (may be None)

    # From usedByEmployeeId (legacy single field)
    async for doc in master.find(
        {"usedByEmployeeId": {"$exists": True, "$ne": None}},
        {"usedByEmployeeId": 1, "usedByEmployeeName": 1},
    ):
        eid = doc.get("usedByEmployeeId")
        if eid and str(eid) not in raw_used_emp:
            raw_used_emp[str(eid)] = doc.get("usedByEmployeeName")

    # From usedByEmployeeIds (new multi field)
    async for doc in master.find(
        {"usedByEmployeeIds": {"$exists": True, "$not": {"$size": 0}}},
        {"usedByEmployeeIds": 1, "usedByEmployeeNames": 1},
    ):
        emp_ids = doc.get("usedByEmployeeIds", [])
        emp_names = doc.get("usedByEmployeeNames", [])
        for i, eid in enumerate(emp_ids):
            if eid and str(eid) not in raw_used_emp:
                raw_used_emp[str(eid)] = emp_names[i] if i < len(emp_names) else None

    # From usedInProfiles (embedded array)
    async for doc in master.find(
        {"usedInProfiles": {"$exists": True, "$ne": []}},
        {"usedInProfiles": 1},
    ):
        for profile in doc.get("usedInProfiles", []):
            eid = profile.get("employeeId")
            if eid and str(eid) not in raw_used_emp:
                raw_used_emp[str(eid)] = None  # name unknown yet

    # ── Batch-resolve missing names (2 DB queries, not N) ────────────────────
    unresolved_ids = [
        str(eid) for eid, name in raw_used_emp.items() if not name
    ]
    if unresolved_ids:
        valid_obj_ids = [ObjectId(i) for i in unresolved_ids if ObjectId.is_valid(i)]
        # employees._id → userId
        emp_to_user: dict[str, str] = {}
        async for emp in employees_col.find(
            {"_id": {"$in": valid_obj_ids}}, {"_id": 1, "userId": 1}
        ):
            emp_to_user[str(emp["_id"])] = str(emp["userId"]) if emp.get("userId") else ""

        # All user IDs we need names for
        need_user_ids = [
            ObjectId(uid)
            for uid in {*emp_to_user.values(), *unresolved_ids}
            if uid and ObjectId.is_valid(uid)
        ]
        user_names: dict[str, str] = {}
        async for user in users_col.find(
            {"_id": {"$in": need_user_ids}}, {"_id": 1, "name": 1}
        ):
            user_names[str(user["_id"])] = user.get("name") or ""

        for eid in unresolved_ids:
            linked = emp_to_user.get(eid)
            name = (user_names.get(linked) if linked else None) or user_names.get(eid)
            if name:
                raw_used_emp[eid] = name

    # ── Build final result ────────────────────────────────────────────────────
    unified_domains = sorted({v for v in [*domains, *domain_groups] if v})
    uploaders = [
        {"id": uid, "name": uname} for uid, uname in uploaders_data.items()
    ]
    used_by_employees = [
        {"id": eid, "name": name or eid} for eid, name in raw_used_emp.items()
    ]

    result = {
        "domains": unified_domains,
        "countries": [c for c in countries if c],
        "states": [s for s in states if s],
        "universities": [u for u in universities if u],
        "designations": [d for d in designations if d],
        "mailSources": [m for m in mail_sources if m],
        "uploaders": uploaders,
        "usedByEmployees": used_by_employees,
    }

    # ── Store in cache ────────────────────────────────────────────────────────
    _DROPDOWN_CACHE = result
    _DROPDOWN_CACHE_AT = now
    return result


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
    query: dict = {
        "isDuplicate": False,
        "hasReply": {"$ne": True},
        "inProfileEmails": {"$ne": True},
    }

    if not filters.get("allowUsed", False):
        query["usageCount"] = {"$in": [0, None]}

    country_values = _filter_values(filters.get("country"))
    state_values = _filter_values(filters.get("state"))
    domain_values = [
        *_filter_values(filters.get("domain")),
        *_filter_values(filters.get("domainGroup") or filters.get("domain_group")),
    ]
    university_values = _filter_values(filters.get("university"))
    mail_source_values = _filter_values(filters.get("mailSource"))
    type_values = _filter_values(filters.get("type"))

    if country_values:
        query["country"] = {"$in": country_values}
    if state_values:
        query["state"] = {"$in": state_values}
    if domain_values:
        query["$or"] = [
            {"domain": {"$in": domain_values}},
            {"domain_group": {"$in": domain_values}},
        ]
    if university_values:
        query["university"] = {"$in": university_values}
    if mail_source_values:
        query["mailSource"] = {"$in": mail_source_values}
    if type_values:
        query.setdefault("$and", []).append({
            "$or": [
                {"industry": {"$in": type_values}},
                {"designation": {"$in": type_values}},
            ]
        })

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
        filters: Filter criteria (country, domain, domain group, university, type)
        daily_limit: Daily limit for sends (used to determine pool size)
        filter_limit: Maximum emails to return from filtered results (0 = no limit)
        employee_id: Current employee ID (to track who claims emails)
    """
    master = get_collection(COLLECTION)
    query: dict = {"isDuplicate": False, "hasReply": {"$ne": True}}
    
    # Always skip emails that are currently locked in a profile. Missing legacy
    # fields are treated as unlocked by using $ne rather than matching False.
    query["inProfileEmails"] = {"$ne": True}

    if not filters.get("allowUsed", False):
        query["usageCount"] = {"$in": [0, None]}

    country_values = _filter_values(filters.get("country"))
    state_values = _filter_values(filters.get("state"))
    domain_values = [
        *_filter_values(filters.get("domain")),
        *_filter_values(filters.get("domainGroup") or filters.get("domain_group")),
    ]
    university_values = _filter_values(filters.get("university"))
    mail_source_values = _filter_values(filters.get("mailSource"))
    type_values = _filter_values(filters.get("type"))

    if country_values:
        query["country"] = {"$in": country_values}
    if state_values:
        query["state"] = {"$in": state_values}
    if domain_values:
        domain_condition = {
            "$or": [
                {"domain": {"$in": domain_values}},
                {"domain_group": {"$in": domain_values}},
            ]
        }
        query.setdefault("$and", []).append(domain_condition)
    if university_values:
        query["university"] = {"$in": university_values}
    if mail_source_values:
        query["mailSource"] = {"$in": mail_source_values}
    if type_values:
        # Append to $and if it exists, otherwise use $or directly
        type_or = {"$or": [
            {"industry": {"$in": type_values}},
            {"designation": {"$in": type_values}},
        ]}
        if "$and" in query:
            query["$and"].append(type_or)
        else:
            query["$or"] = type_or["$or"]

    # A positive filter limit caps the result; zero or missing means no limit.
    fetch_limit = filter_limit if filter_limit > 0 else None

    if fetch_limit is None:
        cursor = master.find(query)
        all_results = serialize_list([d async for d in cursor])
    elif not filters.get("mailSource"):
        # Fetch random sample when mailSource is empty
        pipeline = [
            {"$match": query},
            {"$sample": {"size": fetch_limit * 2}}
        ]
        cursor = master.aggregate(pipeline)
        all_results = serialize_list([d async for d in cursor])
    else:
        # Fetch sequentially when mailSource is specified
        cursor = master.find(query).limit(fetch_limit * 2)  # Fetch extra to account for skipped
        all_results = serialize_list([d async for d in cursor])
    
    # Filter in application code: we no longer skip based on used_by_id since we check inProfileEmails
    # and we want to allow sharing. But just to be safe if there's legacy data, we just append all.
    available_results = []
    for email_record in all_results:
        # All fetched records are valid because we filtered out inProfileEmails = True
        # and usageCount > 0 (if allowUsed was false) at the DB level.
        available_results.append(email_record)
    
    # Return only the requested limit
    return available_results if fetch_limit is None else available_results[:fetch_limit]


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
                "assignedDate": now,
                "updatedAt": now,
            },
            "$inc": {
                "usageCount": 1
            },
            "$addToSet": {
                "usedByEmployeeIds": employee_id,
                "usedByEmployeeNames": employee_name
            }
        },
    )


async def release_email_locks(master_ids: list[str]) -> None:
    """Release locks for emails when they are removed from a profile."""
    from datetime import datetime, timezone
    master = get_collection(COLLECTION)
    from bson import ObjectId

    object_ids = [ObjectId(mid) for mid in master_ids if ObjectId.is_valid(mid)]
    if not object_ids:
        return
        
    now = datetime.now(timezone.utc)
    await master.update_many(
        {"_id": {"$in": object_ids}},
        {
            "$set": {
                "inProfileEmails": False,
                "updatedAt": now,
            }
        }
    )


async def mark_email_sent(master_email_id: str) -> None:
    """Record the successful send time used by the reuse cooldown policy."""
    from bson import ObjectId

    if not ObjectId.is_valid(master_email_id):
        return

    now = datetime.now(timezone.utc)
    master = get_collection(COLLECTION)
    await master.update_one(
        {"_id": ObjectId(master_email_id)},
        {"$set": {"lastUsedAt": now, "updatedAt": now}},
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
