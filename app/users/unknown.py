import secrets
import re
from datetime import datetime, timezone

from bson import ObjectId

from app.core.exceptions import ConflictException
from app.core.security import hash_password
from app.database.mongodb import get_collection

UNKNOWN_USER_ID = "000000000000000000000001"
UNKNOWN_EMPLOYEE_ID = "000000000000000000000002"
UNKNOWN_MARKER = "unknown"
DELETED_USERS_COLLECTION = "deleted_user_mappings"


async def ensure_unknown_identity() -> tuple[str, str]:
    users = get_collection("users")
    employees = get_collection("employees")
    user_object_id = ObjectId(UNKNOWN_USER_ID)
    employee_object_id = ObjectId(UNKNOWN_EMPLOYEE_ID)

    user = await users.find_one({"_id": user_object_id})
    if user and user.get("systemAccount") != UNKNOWN_MARKER:
        raise ConflictException("Reserved Unknown user ID is already in use")
    email_owner = await users.find_one({"email": "unknown@system.invalid"})
    if email_owner and email_owner.get("_id") != user_object_id:
        raise ConflictException("Reserved Unknown email address is already in use")
    if not user:
        password = secrets.token_urlsafe(48)
        now = datetime.now(timezone.utc)
        await users.insert_one({
            "_id": user_object_id,
            "name": "Unknown",
            "email": "unknown@system.invalid",
            "phoneNumber": None,
            "accessLevel": "full",
            "password": hash_password(password),
            "passwordEncrypted": "",
            "role": "employee",
            "status": "inactive",
            "branch": None,
            "systemAccount": UNKNOWN_MARKER,
            "createdAt": now,
            "updatedAt": now,
        })
    employee = await employees.find_one({"_id": employee_object_id})
    if employee and employee.get("systemAccount") != UNKNOWN_MARKER:
        raise ConflictException("Reserved Unknown employee ID is already in use")
    if not employee:
        await employees.insert_one({
            "_id": employee_object_id,
            "userId": UNKNOWN_USER_ID,
            "branch": None,
            "department": None,
            "assignedToAdmin": None,
            "status": "inactive",
            "systemAccount": UNKNOWN_MARKER,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        })

    return UNKNOWN_USER_ID, UNKNOWN_EMPLOYEE_ID


async def resolve_unknown_employee_ids(
    branch: str | None = None,
    assigned_to_admin: str | None = None,
    include_all: bool = True,
) -> list[str]:
    mappings = get_collection(DELETED_USERS_COLLECTION)
    ids = {UNKNOWN_EMPLOYEE_ID}
    query = {}
    if not include_all:
        if assigned_to_admin is not None:
            query = {"assignedToAdmin": assigned_to_admin}
        elif branch:
            query = {
                "branch": {
                    "$regex": f"^{re.escape(branch.strip())}$",
                    "$options": "i",
                }
            }
        else:
            return sorted(ids)
    async for mapping in mappings.find(query, {"employeeId": 1, "userId": 1, "branch": 1, "assignedToAdmin": 1}):
        if not include_all:
            if assigned_to_admin is not None:
                if str(mapping.get("assignedToAdmin") or "") != assigned_to_admin:
                    continue
            elif branch:
                if (
                    str(mapping.get("branch") or "").strip().casefold()
                    != branch.strip().casefold()
                ):
                    continue
            else:
                continue
        for field in ("employeeId", "userId"):
            value = mapping.get(field)
            if value:
                ids.add(str(value))
    return sorted(ids)


async def find_legacy_employee_id_for_user(
    user_id: str,
    display_name: str,
) -> str | None:
    """Recover a unique orphaned profile owner from the old employee-delete flow."""
    profiles = get_collection("profiles")
    employees = get_collection("employees")
    candidate_ids: set[str] = set()
    async for profile in profiles.find(
        {"employeeName": display_name},
        {"employeeId": 1},
    ):
        employee_id = str(profile.get("employeeId") or "")
        if not employee_id or employee_id == user_id:
            continue
        employee_doc = await employees.find_one(
            {"_id": ObjectId(employee_id)}
            if ObjectId.is_valid(employee_id)
            else {"_id": employee_id},
            {"_id": 1},
        )
        if not employee_doc:
            candidate_ids.add(employee_id)
    return next(iter(candidate_ids)) if len(candidate_ids) == 1 else None


async def preserve_deleted_user_data(
    user_id: str,
    employee_id: str | None,
    deleted_name: str,
    branch: str | None = None,
    assigned_to_admin: str | None = None,
) -> None:
    unknown_user_id, unknown_employee_id = await ensure_unknown_identity()
    now = datetime.now(timezone.utc)
    mappings = get_collection(DELETED_USERS_COLLECTION)
    await mappings.update_one(
        {"_id": user_id},
        {"$set": {
            "userId": user_id,
            "employeeId": employee_id,
            "deletedName": deleted_name,
            "branch": branch,
            "assignedToAdmin": assigned_to_admin,
            "deletedAt": now,
        }},
        upsert=True,
    )

    profiles = get_collection("profiles")
    owner_ids = {user_id}
    if employee_id:
        owner_ids.add(employee_id)
    owner_values: list[str | ObjectId] = list(owner_ids) + [
        ObjectId(value) for value in owner_ids if ObjectId.is_valid(value)
    ]
    await profiles.update_many(
        {"employeeId": {"$in": owner_values}},
        {"$set": {"employeeName": "Unknown", "updatedAt": now}},
    )
    await get_collection("emails").update_many(
        {"employeeId": {"$in": owner_values}},
        {"$set": {"uploadedByName": "Unknown", "updatedAt": now}},
    )

    master = get_collection("email_master")
    await master.update_many(
        {"uploadedBy": user_id},
        {"$set": {
            "uploadedBy": unknown_user_id,
            "uploadedByName": "Unknown",
            "updatedAt": now,
        }},
    )
    await master.update_many(
        {"usedByEmployeeId": {"$in": list(owner_values)}},
        {"$set": {
            "usedByEmployeeId": unknown_employee_id,
            "usedByEmployeeName": "Unknown",
            "updatedAt": now,
        }},
    )
    await master.update_many(
        {"replyMarkedBy": {"$in": [user_id, ObjectId(user_id)] if ObjectId.is_valid(user_id) else [user_id]}},
        {"$set": {
            "replyMarkedBy": unknown_user_id,
            "replyMarkedByName": "Unknown",
            "updatedAt": now,
        }},
    )
    await master.update_many(
        {"usedInProfiles.employeeId": {"$in": list(owner_values)}},
        {"$set": {"usedInProfiles.$[profile].employeeName": "Unknown"}},
        array_filters=[{"profile.employeeId": {"$in": list(owner_values)}}],
    )

    # Cached uploader dropdown values are maintained separately from records.
    dropdowns = get_collection("filter_dropdowns")
    await dropdowns.update_one(
        {"_id": "global"},
        {"$pull": {"uploaders": {"id": user_id}}},
    )
    await dropdowns.update_one(
        {"_id": "global"},
        {"$addToSet": {"uploaders": {"id": unknown_user_id, "name": "Unknown"}}},
    )
    from app.email_master.service import invalidate_dropdown_cache

    await invalidate_dropdown_cache()
