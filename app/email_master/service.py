from pandas import date_range
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
FILTER_DROPDOWN_COLLECTION = "filter_dropdowns"
FILTER_DROPDOWN_ID = "global"

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


def _apply_profile_email_domain_limits(
    records: list[dict], requested_limit: int
) -> list[dict]:
    """Keep Gmail recipients unrestricted and cap other domains."""
    if requested_limit <= 0:
        domain_limit = None
    else:
        domain_limit = ((requested_limit - 1) // 100 + 1) * 5

    domain_counts: dict[str, int] = {}
    available: list[dict] = []
    for record in records:
        email = str(record.get("email") or "").strip()
        domain = email.rpartition("@")[2].casefold()
        if domain == "gmail.com" or not domain or domain_limit is None:
            available.append(record)
            continue
        if domain_counts.get(domain, 0) >= domain_limit:
            continue
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        available.append(record)
    return available


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
    existing_emails = {
        doc["email"]: doc["_id"] async for doc in existing_cursor
    }

    docs_to_insert: list[dict] = []
    seen_in_batch: set[str] = set()
    duplicate_existing_ids: set[Any] = set()
    unique_count = 0
    duplicate_count = 0

    for row in valid_rows:
        email_addr = row["email"]
        is_dup = email_addr in existing_emails or email_addr in seen_in_batch
        if is_dup:
            duplicate_count += 1
            if email_addr in existing_emails:
                duplicate_existing_ids.add(existing_emails[email_addr])
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
    if duplicate_existing_ids:
        await master.update_many(
            {"_id": {"$in": list(duplicate_existing_ids)}},
            {
                "$set": {
                    "uploadedDate": datetime.now(timezone.utc),
                    "uploadedBy": uploaded_by_id,
                    "uploadedByName": uploaded_by_name,
                }
            },
        )
    if docs_to_insert:
        await master.insert_many(docs_to_insert)
        await _update_dropdown_filters(docs_to_insert, uploaded_by_id, uploaded_by_name)

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
    # ── Date filter ───────────────────────────────────────────────────────────
    date_filter: bool = False,
    date_range: str | None = None,   # "last_30_days" | "last_3_months" | "custom"
    start_date: date | None = None,  # used when date_range == "custom"
    end_date: date | None = None,    # used when date_range == "custom"
) -> dict:
    """List emails from GLOBAL pool with optional filters.
    
    All filter params support multi-value lists — values are combined with OR logic.
    Comma-separated strings (e.g. 'India,USA') are also accepted and split automatically.
    
    Date filter:
      date_filter=True + date_range='last_30_days'  → uploaded in last 30 days
      date_filter=True + date_range='last_3_months' → uploaded in last 90 days
      date_filter=True + date_range='custom'        → between start_date and end_date
    """
    master = get_collection(COLLECTION)
    query: dict = {}
    and_clauses: list[dict] = []

    # Helper: normalise a raw filter value (str, list[str], or None)
    # into a clean de-duplicated list, splitting on commas.
    def _vals(v) -> list[str]:
        return _filter_values(v)

    # ── country (case-insensitive exact match) ───────────────────────────────
    countries = _vals(country)
    if countries:
        country_rx = [re.compile(f"^{re.escape(c)}$", re.IGNORECASE) for c in countries]
        query["country"] = {"$in": country_rx} if len(country_rx) > 1 else country_rx[0]

    # ── state (case-insensitive exact match) ─────────────────────────────────
    states = _vals(state)
    if states:
        state_rx = [re.compile(f"^{re.escape(s)}$", re.IGNORECASE) for s in states]
        query["state"] = {"$in": state_rx} if len(state_rx) > 1 else state_rx[0]

    # ── domain / domain_group (case-insensitive, searches both fields) ────────
    domains = _vals(domain)
    if domains:
        domain_rx = [re.compile(f"^{re.escape(d)}$", re.IGNORECASE) for d in domains]
        if len(domain_rx) == 1:
            and_clauses.append({"$or": [
                {"domain": domain_rx[0]},
                {"domain_group": domain_rx[0]},
            ]})
        else:
            and_clauses.append({"$or": [
                {"domain": {"$in": domain_rx}},
                {"domain_group": {"$in": domain_rx}},
            ]})

    # ── university (case-insensitive partial match) ───────────────────────────
    universities = _vals(university)
    if universities:
        if len(universities) == 1:
            query["university"] = {"$regex": re.escape(universities[0]), "$options": "i"}
        else:
            and_clauses.append({"$or": [
                {"university": {"$regex": re.escape(u), "$options": "i"}}
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

    # ── mailSource (case-insensitive exact match) ─────────────────────────────
    mail_sources = _vals(mail_source)
    if mail_sources:
        mail_rx = [re.compile(f"^{re.escape(m)}$", re.IGNORECASE) for m in mail_sources]
        query["mailSource"] = {"$in": mail_rx} if len(mail_rx) > 1 else mail_rx[0]

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

    # ── date filter ───────────────────────────────────────────────────────────
    if date_filter and date_range:
        now = datetime.now(timezone.utc)
        if date_range == "last_30_days":
            query["uploadedDate"] = {"$gte": now - timedelta(days=30)}
        elif date_range == "last_3_months":
            query["uploadedDate"] = {"$gte": now - timedelta(days=90)}
        elif date_range == "custom":
            date_query: dict = {}
            if start_date:
                date_query["$gte"] = datetime(
                    start_date.year, start_date.month, start_date.day,
                    0, 0, 0, tzinfo=timezone.utc
                )
            if end_date:
                date_query["$lte"] = datetime(
                    end_date.year, end_date.month, end_date.day,
                    23, 59, 59, tzinfo=timezone.utc
                )
            if date_query:
                query["uploadedDate"] = date_query

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
    
    docs = await _enrich_emails_with_profile_names(docs)
    # Enrich with employee names (batch lookups — no N+1)
    docs = await _enrich_emails_with_employee_names(docs)
    
    return build_paginated_response(docs, total, params)


async def _enrich_emails_with_profile_names(docs: list[dict]) -> list[dict]:
    """Add names of profiles that currently contain each email-master record."""
    if not docs:
        return docs

    from bson import ObjectId

    master_ids = [str(doc.get("id") or doc.get("_id")) for doc in docs]
    profile_emails = get_collection("profile_emails")
    profile_ids_by_master: dict[str, set[str]] = {}
    async for profile_email in profile_emails.find(
        {"masterEmailId": {"$in": master_ids}},
        {"masterEmailId": 1, "profileId": 1},
    ):
        master_id = str(profile_email.get("masterEmailId") or "")
        profile_id = str(profile_email.get("profileId") or "")
        if master_id and profile_id:
            profile_ids_by_master.setdefault(master_id, set()).add(profile_id)

    profile_ids = {
        profile_id
        for ids in profile_ids_by_master.values()
        for profile_id in ids
    }
    valid_profile_object_ids = [
        ObjectId(profile_id)
        for profile_id in profile_ids
        if ObjectId.is_valid(profile_id)
    ]
    profiles_by_id: dict[str, str] = {}
    active_profile_ids: set[str] = set()
    if valid_profile_object_ids:
        profiles = get_collection("profiles")
        async for profile in profiles.find(
            {"_id": {"$in": valid_profile_object_ids}},
            {"_id": 1, "profileName": 1},
        ):
            profile_id = str(profile["_id"])
            active_profile_ids.add(profile_id)
            profiles_by_id[profile_id] = profile.get("profileName") or ""

    for doc, master_id in zip(docs, master_ids):
        stored_names = {
            str(name).strip()
            for name in doc.get("profileNames", [])
            if name and str(name).strip()
        }
        current_names = {
            profiles_by_id[profile_id]
            for profile_id in profile_ids_by_master.get(master_id, set())
            if profiles_by_id.get(profile_id)
        }
        doc["profileNames"] = sorted(stored_names | current_names)
        doc["inProfileEmails"] = bool(
            profile_ids_by_master.get(master_id, set()) & active_profile_ids
        )

    return docs


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
    
    doc = (await _enrich_emails_with_profile_names([doc]))[0]
    # Enrich with employee name
    docs = await _enrich_emails_with_employee_names([doc])
    return docs[0] if docs else doc


async def mark_email_reply(
    email: str,
    reason: str,
    custom_reason: str | None,
    marked_by: str,
    marked_by_name: str | None = None,
    phone_no: str | None = None,
) -> dict:
    """Mark an address as replied and remove it from active profile email lists."""
    master = get_collection(COLLECTION)
    normalized_email = email.strip().lower()
    now = datetime.now(timezone.utc)
    update = {
        "hasReply": True,
        "replyReason": reason,
        "replyCustomReason": custom_reason,
        "phone_no":phone_no,
        "replyMarkedAt": now,
        "replyMarkedBy": marked_by,
        "replyMarkedByName": marked_by_name or marked_by,
        "updatedAt": now,
    }
    result = await master.update_many(
        {"email": {"$regex": f"^{normalized_email}$", "$options": "i"}},
        {"$set": update},
    )
    verify_mail = await master.find_one({"email": {"$regex": f"^{normalized_email}$", "$options": "i"}})

    if verify_mail is None:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")

    if verify_mail['hasReply'] == True:
        from app.core.exceptions import AlreadyExistsException
        raise AlreadyExistsException("Email already marked as replied")

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
    users = get_collection("users")
    scope: set[str] = {str(user_id)}
    own_employee = await employees.find_one({"userId": user_id})
    if not own_employee:
        from bson import ObjectId

        if ObjectId.is_valid(user_id):
            own_employee = await employees.find_one(
                {"userId": ObjectId(user_id)}
            )

    own_employee_id = str(own_employee["_id"]) if own_employee else None
    if own_employee_id:
        scope.add(own_employee_id)

    if role != "admin" or not own_employee_id:
        return scope

    # For admin, get all employees in the same branch
    admin_branch = own_employee.get("branch") if own_employee else None
    if not admin_branch:
        from app.utils.response import to_object_id
        admin_u = await users.find_one({"_id": to_object_id(user_id)}, {"branch": 1})
        admin_branch = (admin_u or {}).get("branch")

    if admin_branch:
        import re
        branch_regex = {"$regex": f"^{re.escape(str(admin_branch).strip())}$", "$options": "i"} 

        # Only include branch users whose role is 'employee'
        branch_users = [
            u async for u in users.find(
                {"branch": branch_regex, "role": "employee"},
                {"_id": 1}
            )
        ]
        for u in branch_users:
            scope.add(str(u["_id"]))

        branch_uids = [str(u["_id"]) for u in branch_users] + [u["_id"] for u in branch_users]
        assigned = employees.find({
            "userId": {"$in": branch_uids}
        }, {"_id": 1, "userId": 1})
    else:
        assigned = employees.find({
            "assignedToAdmin": {"$in": [own_employee_id, to_object_id(own_employee_id)]}
        }, {"_id": 1, "userId": 1})

    async for employee in assigned:
        scope.add(str(employee["_id"]))
        if employee.get("userId"):
            scope.add(str(employee["userId"]))

    # Always ensure admin's own IDs are included
    scope.add(str(user_id))
    if own_employee_id:
        scope.add(own_employee_id)

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
    phone_no = payload.get("phone_no", doc.get("phone_no"))
    custom_reason = payload.get("customReason", doc.get("replyCustomReason"))
    if has_reply and not reason:
        raise BadRequestException("reason is required when hasReply is true")

    now = datetime.now(timezone.utc)
    marked_by_name = await get_user_display_name(marked_by)
    update = {
        "hasReply": has_reply,
        "replyReason": reason if has_reply else None,
        "phone_no": phone_no if has_reply else None,
        "replyCustomReason": custom_reason if has_reply else None,
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
    """FULL ADMIN + SUPER ADMIN: Delete email from global pool."""
    master = get_collection(COLLECTION)
    result = await master.delete_one({"_id": to_object_id(email_id)})
    if result.deleted_count == 0:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")


async def update_email(email_id: str, update_data: dict) -> dict:
    """FULL ADMIN + SUPER ADMIN: Update editable contact fields on an email_master record.
    Email address cannot be changed. Only provided fields are updated."""
    # Safety: never allow email address to be changed
    update_data.pop("email", None)

    if not update_data:
        from app.core.exceptions import BadRequestException
        raise BadRequestException("No fields provided to update")

    master = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    update_data["updatedAt"] = now

    updated = await master.find_one_and_update(
        {"_id": to_object_id(email_id)},
        {"$set": update_data},
        return_document=True,
    )
    if not updated:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Email record not found")

    # Invalidate dropdown cache so updated country/domain etc. appear immediately
    invalidate_dropdown_cache()

    # Replicate updated fields to all associated profile_emails working copies
    profile_emails_col = get_collection("profile_emails")
    # Only copy fields that exist in profile_emails schema/model
    allowed_profile_fields = {
        "fullName", "university", "website", "country", "state",
        "city", "domain", "industry", "designation", "phone", "linkedin"
    }
    replicate_data = {k: v for k, v in update_data.items() if k in allowed_profile_fields}
    if replicate_data:
        replicate_data["updatedAt"] = now
        await profile_emails_col.update_many(
            {"masterEmailId": str(email_id)},
            {"$set": replicate_data},
        )

    return serialize_doc(updated)




async def delete_emails_filtered(
    start_date: date | None = None,
    end_date: date | None = None,
    uploaded_by: str | None = None,
    domains: str | None = None,
    country: str | None = None,
) -> dict:
    """Delete email-master records based on optional filters."""
    query = {}
    
    if start_date or end_date:
        date_query = {}
        if start_date:
            start_datetime = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
            date_query["$gte"] = start_datetime
        if end_date:
            end_exclusive = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
            date_query["$lt"] = end_exclusive
        query["uploadedDate"] = date_query
        
    and_conditions = []
    
    if uploaded_by:
        and_conditions.append({
            "$or": [
                {"uploadedBy": uploaded_by},
                {"uploadedByName": {"$regex": f"^{re.escape(uploaded_by)}$", "$options": "i"}}
            ]
        })
        
    if domains:
        domain_list = _filter_values(domains)
        if domain_list:
            and_conditions.append({
                "$or": [
                    {"domain": {"$in": domain_list}},
                    {"domain_group": {"$in": domain_list}}
                ]
            })
            
    if country:
        country_list = _filter_values(country)
        if country_list:
            query["country"] = {"$in": country_list}

    if and_conditions:
        query["$and"] = and_conditions

    if not query:
        raise BadRequestException(" At least one filter must be provided to prevent accidental full deletion.")

    master = get_collection(COLLECTION)
    result = await master.delete_many(query)
    
    return {
        "deletedCount": result.deleted_count,
        "filtersApplied": {
            "startDate": start_date.isoformat() if start_date else None,
            "endDate": end_date.isoformat() if end_date else None,
            "uploadedBy": uploaded_by,
            "domains": domains,
            "country": country,
        }
    }


async def _update_dropdown_filters(docs_to_insert: list[dict], uploaded_by_id: str, uploaded_by_name: str) -> None:
    if not docs_to_insert:
        return

    def values_for(field: str) -> set[str]:
        values: set[str] = set()
        for doc in docs_to_insert:
            raw_value = doc.get(field)
            if raw_value is not None and str(raw_value).strip():
                values.add(str(raw_value).strip())
        return values

    update_data = {
        field: {"$each": sorted(values)}
        for field, values in {
            "domains": values_for("domain"),
            "countries": values_for("country"),
            "states": values_for("state"),
            "universities": values_for("university"),
            "designations": values_for("designation"),
            "mailSources": values_for("mailSource"),
        }.items()
        if values
    }

    if uploaded_by_id:
        update_data["uploaders"] = {"id": uploaded_by_id, "name": uploaded_by_name or uploaded_by_id}

    if update_data:
        filter_col = get_collection(FILTER_DROPDOWN_COLLECTION)
        await filter_col.update_one(
            {"_id": FILTER_DROPDOWN_ID},
            {
                "$addToSet": update_data,
                "$set": {"lastUpdated": datetime.now(timezone.utc)}
            },
            upsert=True
        )
        invalidate_dropdown_cache()


async def rebuild_dropdown_filters() -> dict:
    """SUPER ADMIN ONLY: Rebuild filter_dropdowns from scratch by scanning
    the current email_master collection. Call after bulk deletions to remove
    stale country/domain/state options."""
    master = get_collection(COLLECTION)
    filter_col = get_collection(FILTER_DROPDOWN_COLLECTION)

    pipeline = [
        {
            "$group": {
                "_id": None,
                "countries":      {"$addToSet": "$country"},
                "states":         {"$addToSet": "$state"},
                "universities":   {"$addToSet": "$university"},
                "designations":   {"$addToSet": "$designation"},
                "mailSources":    {"$addToSet": "$mailSource"},
                "domains":        {"$addToSet": "$domain"},
            }
        }
    ]

    result = await master.aggregate(pipeline).to_list(1)

    def _clean(values: list) -> list:
        return sorted({str(v).strip() for v in (values or []) if v and str(v).strip()})

    if result:
        row = result[0]
        all_domains = _clean(row.get("domains"))
        countries    = _clean(row.get("countries"))
        states       = _clean(row.get("states"))
        universities = _clean(row.get("universities"))
        designations = _clean(row.get("designations"))
        mail_sources = _clean(row.get("mailSources"))
    else:
        all_domains = countries = states = universities = designations = mail_sources = []

    # Rebuild unique uploader list
    uploaders: list[dict] = []
    seen_ids: set[str] = set()
    async for doc in master.find({}, {"uploadedBy": 1, "uploadedByName": 1}):
        uid = str(doc.get("uploadedBy") or "").strip()
        uname = str(doc.get("uploadedByName") or "").strip()
        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            uploaders.append({"id": uid, "name": uname or uid})

    new_doc = {
        "_id":             FILTER_DROPDOWN_ID,
        "countries":       countries,
        "states":          states,
        "universities":    universities,
        "designations":    designations,
        "mailSources":     mail_sources,
        "domains":         all_domains,
        "uploaders":       uploaders,
        "usedByEmployees": [],
        "lastUpdated":     datetime.now(timezone.utc),
    }

    # Full replace — removes any values no longer in email_master
    await filter_col.replace_one({"_id": FILTER_DROPDOWN_ID}, new_doc, upsert=True)
    invalidate_dropdown_cache()

    return {
        "countries":    len(countries),
        "states":       len(states),
        "universities": len(universities),
        "designations": len(designations),
        "mailSources":  len(mail_sources),
        "domains":      len(all_domains),
        "uploaders":    len(uploaders),
    }


async def get_dropdown_options() -> dict:
    """Returns dropdown options from the pre-computed filter_dropdowns collection."""
    global _DROPDOWN_CACHE, _DROPDOWN_CACHE_AT
    now = datetime.now(timezone.utc)
    
    if _DROPDOWN_CACHE is not None and _DROPDOWN_CACHE_AT is not None:
        age = (now - _DROPDOWN_CACHE_AT).total_seconds()
        if age < _DROPDOWN_CACHE_TTL_SECONDS:
            return _DROPDOWN_CACHE
            
    filter_col = get_collection(FILTER_DROPDOWN_COLLECTION)
    doc = await filter_col.find_one({"_id": FILTER_DROPDOWN_ID})
    
    if not doc:
        result = {
            "domains": [], "countries": [], "states": [], "universities": [],
            "designations": [], "mailSources": [], "uploaders": [], "usedByEmployees": []
        }
    else:
        result = {
            key: doc.get(key, [])
            for key in ("domains", "countries", "states", "universities", "designations", "mailSources", "uploaders", "usedByEmployees")
        }

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
        country_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in country_values]
        query["country"] = {"$in": country_rx}
    if state_values:
        state_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in state_values]
        query["state"] = {"$in": state_rx}
    if domain_values:
        domain_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in domain_values]
        domain_condition = {
            "$or": [
                {"domain": {"$in": domain_rx}},
                {"domain_group": {"$in": domain_rx}},
            ]
        }
        query.setdefault("$and", []).append(domain_condition)
    if university_values:
        if len(university_values) == 1:
            query["university"] = {"$regex": re.escape(university_values[0]), "$options": "i"}
        else:
            uni_or = {"$or": [{"university": {"$regex": re.escape(u), "$options": "i"}} for u in university_values]}
            query.setdefault("$and", []).append(uni_or)
    if mail_source_values:
        mail_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in mail_source_values]
        query["mailSource"] = {"$in": mail_rx}
    if type_values:
        # Case-insensitive match on industry and designation
        type_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in type_values]
        type_or = {"$or": [
            {"industry": {"$in": type_rx}},
            {"designation": {"$in": type_rx}},
        ]}
        if "$and" in query:
            query["$and"].append(type_or)
        else:
            query["$or"] = type_or["$or"]

    # ── date filter (from profile filters) ───────────────────────────────────
    if filters.get("date_filter") and filters.get("date_range"):
        now = datetime.now(timezone.utc)
        date_range = filters["date_range"]
        if date_range == "last_30_days":
            query["uploadedDate"] = {"$gte": now - timedelta(days=30)}
        elif date_range == "last_3_months":
            query["uploadedDate"] = {"$gte": now - timedelta(days=90)}
        elif date_range == "custom":
            date_q: dict = {}
            raw_start = filters.get("start_date")
            raw_end = filters.get("end_date")
            if raw_start:
                try:
                    from datetime import date as _date
                    parts = raw_start.split("-")
                    # Support YYYY-MM-DD and DD-MM-YYYY
                    if len(parts[0]) == 4:
                        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                    else:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    date_q["$gte"] = datetime(y, m, d, 0, 0, 0, tzinfo=timezone.utc)
                except Exception:
                    pass
            if raw_end:
                try:
                    parts = raw_end.split("-")
                    if len(parts[0]) == 4:
                        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                    else:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    date_q["$lte"] = datetime(y, m, d, 23, 59, 59, tzinfo=timezone.utc)
                except Exception:
                    pass
            if date_q:
                query["uploadedDate"] = date_q

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
        country_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in country_values]
        query["country"] = {"$in": country_rx}
    if state_values:
        state_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in state_values]
        query["state"] = {"$in": state_rx}
    if domain_values:
        domain_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in domain_values]
        domain_condition = {
            "$or": [
                {"domain": {"$in": domain_rx}},
                {"domain_group": {"$in": domain_rx}},
            ]
        }
        query.setdefault("$and", []).append(domain_condition)
    if university_values:
        if len(university_values) == 1:
            query["university"] = {"$regex": re.escape(university_values[0]), "$options": "i"}
        else:
            uni_or = {"$or": [{"university": {"$regex": re.escape(u), "$options": "i"}} for u in university_values]}
            query.setdefault("$and", []).append(uni_or)
    if mail_source_values:
        mail_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in mail_source_values]
        query["mailSource"] = {"$in": mail_rx}
    if type_values:
        # Case-insensitive match on industry and designation
        type_rx = [re.compile(f"^{re.escape(v)}$", re.IGNORECASE) for v in type_values]
        type_or = {"$or": [
            {"industry": {"$in": type_rx}},
            {"designation": {"$in": type_rx}},
        ]}
        if "$and" in query:
            query["$and"].append(type_or)
        else:
            query["$or"] = type_or["$or"]

    # ── date filter (from profile filters) ───────────────────────────────────
    if filters.get("date_filter") and filters.get("date_range"):
        now = datetime.now(timezone.utc)
        date_range = filters["date_range"]
        if date_range == "last_30_days":
            query["uploadedDate"] = {"$gte": now - timedelta(days=30)}
        elif date_range == "last_3_months":
            query["uploadedDate"] = {"$gte": now - timedelta(days=90)}
        elif date_range == "custom":
            date_q: dict = {}
            raw_start = filters.get("start_date")
            raw_end = filters.get("end_date")
            if raw_start:
                try:
                    from datetime import date as _date
                    parts = raw_start.split("-")
                    # Support YYYY-MM-DD and DD-MM-YYYY
                    if len(parts[0]) == 4:
                        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                    else:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    date_q["$gte"] = datetime(y, m, d, 0, 0, 0, tzinfo=timezone.utc)
                except Exception:
                    pass
            if raw_end:
                try:
                    parts = raw_end.split("-")
                    if len(parts[0]) == 4:
                        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                    else:
                        d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                    date_q["$lte"] = datetime(y, m, d, 23, 59, 59, tzinfo=timezone.utc)
                except Exception:
                    pass
            if date_q:
                query["uploadedDate"] = date_q

    # A positive filter limit caps the result; zero or missing means no limit.
    fetch_limit = filter_limit if filter_limit > 0 else None

    if fetch_limit is None:
        cursor = master.find(query)
        all_results = serialize_list([d async for d in cursor])
        return _apply_profile_email_domain_limits(all_results, 0)

    matching_count = await master.count_documents(query)
    if matching_count == 0:
        return []

    sample_size = min(matching_count, max(fetch_limit * 2, fetch_limit + 100))
    while True:
        if filters.get("mailSource"):
            cursor = master.find(query).limit(sample_size)
        else:
            cursor = master.aggregate([
                {"$match": query},
                {"$sample": {"size": sample_size}},
            ])
        candidates = serialize_list([doc async for doc in cursor])
        # Apply Gmail exclusion and per-domain limits only after the profile
        # filters have selected the candidate records.
        available_results = _apply_profile_email_domain_limits(
            candidates, fetch_limit
        )
        if len(available_results) >= fetch_limit or sample_size >= matching_count:
            return available_results[:fetch_limit]
        sample_size = min(matching_count, sample_size * 2)


async def mark_used_in_profile(
    master_ids: list[str],
    profile_id: str,
    employee_id: str,
    profile_name: str,
) -> None:
    """Record profile usage and permanently retain each profile name."""
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
                },
                "profileNames": profile_name,
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


async def _get_user_name_and_email(user_id: str) -> tuple[str, str | None]:
    """Return (display_name, email) for a given user or employee ID."""
    from bson import ObjectId

    users = get_collection("users")
    employees = get_collection("employees")
    object_id = ObjectId(user_id) if ObjectId.is_valid(user_id) else None

    # Try direct user lookup first
    user = None
    for q in ([{"_id": object_id}, {"id": user_id}] if object_id else [{"id": user_id}]):
        user = await users.find_one(q, {"name": 1, "email": 1})
        if user:
            break

    if user:
        name = user.get("name") or user.get("email") or user_id
        email = user.get("email")
        return name, email

    # Fall back: treat user_id as employee ID and resolve via employee → user link
    employee = None
    emp_queries = [{"userId": user_id}]
    if object_id:
        emp_queries.extend([{"userId": object_id}, {"_id": object_id}])
    for q in emp_queries:
        employee = await employees.find_one(q, {"userId": 1})
        if employee:
            break

    employee_user_id = (employee or {}).get("userId")
    if employee_user_id:
        emp_user_q = (
            {"_id": ObjectId(str(employee_user_id))}
            if ObjectId.is_valid(str(employee_user_id))
            else {"_id": employee_user_id}
        )
        user = await users.find_one(emp_user_q, {"name": 1, "email": 1})

    name = (user or {}).get("name") or (user or {}).get("email") or user_id
    email = (user or {}).get("email")
    return name, email


async def get_reply_stats(
    user_id: str | None = None,
    role: str | None = None,
) -> dict:
    """Get aggregated statistics for email replies, broken down by handler."""
    master = get_collection(COLLECTION)
    query: dict = {"hasReply": True}

    if user_id and role:
        marker_scope = await _get_reply_marker_scope(user_id, role)
        if marker_scope is not None:
            query["replyMarkedBy"] = {"$in": list(marker_scope)}

    total_replies = await master.count_documents(query)
    converted_count = await master.count_documents({**query, "replyReason": "converted"})
    other_count = await master.count_documents({**query, "replyReason": "other"})

    pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": {
                    "markedBy": "$replyMarkedBy",
                    "markedByName": "$replyMarkedByName"
                },
                "total": {"$sum": 1},
                "converted": {
                    "$sum": {"$cond": [{"$eq": ["$replyReason", "converted"]}, 1, 0]}
                },
                "other": {
                    "$sum": {"$cond": [{"$eq": ["$replyReason", "other"]}, 1, 0]}
                },
            }
        },
        {"$sort": {"total": -1}}
    ]

    results = await master.aggregate(pipeline).to_list(None)

    breakdown = []
    for r in results:
        marked_by_id = r["_id"]["markedBy"]
        marked_by_name = r["_id"]["markedByName"]
        handler_email: str | None = None

        # Resolve name + email together when the stored name is missing/stale
        if marked_by_id and (not marked_by_name or str(marked_by_name) == str(marked_by_id)):
            marked_by_name, handler_email = await _get_user_name_and_email(str(marked_by_id))
        elif marked_by_id:
            # Name already stored — still fetch email
            _, handler_email = await _get_user_name_and_email(str(marked_by_id))

        breakdown.append({
            "handlerId": marked_by_id,
            "handlerName": marked_by_name or marked_by_id or "Unknown",
            "handlerEmail": handler_email,
            "totalReplies": r["total"],
            "converted": r["converted"],
            "other": r["other"],
        })

    return {
        "summary": {
            "totalReplies": total_replies,
            "convertedCount": converted_count,
            "otherCount": other_count,
        },
        "breakdown": breakdown
    }
