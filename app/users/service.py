from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.core.exceptions import (
    BadRequestException,
    ConflictException,
    ForbiddenException,
    NotFoundException,
)
from app.core.security import encrypt_password, hash_password, verify_password
from app.database.mongodb import get_collection
from app.users.model import AdminAccessLevel, UserRole, build_user_document
from app.users.schema import UserCreate, UserUpdate, PasswordUpdate
from app.core.dependencies import CurrentUser
from app.users.unknown import (
    UNKNOWN_EMPLOYEE_ID,
    UNKNOWN_MARKER,
    UNKNOWN_USER_ID,
    preserve_deleted_user_data,
)
from app.utils.response import (
    serialize_doc,
    serialize_list_users_with_password,
    serialize_user,
    to_object_id,
)

COLLECTION = "users"
PROFILE_PICTURE_MAX_BYTES = 5 * 1024 * 1024
_PROFILE_PICTURE_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


def _profile_picture_media_type(contents: bytes) -> str | None:
    for signature, media_type in _PROFILE_PICTURE_TYPES:
        if contents.startswith(signature):
            return media_type
    if len(contents) >= 12 and contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return "image/webp"
    return None


def _profile_picture_path(user_id: str) -> Path:
    return settings.profile_picture_storage_path / str(to_object_id(user_id))


def _profile_picture_url(user_id: str) -> str | None:
    if not _profile_picture_path(user_id).is_file():
        return None
    return f"/users/{to_object_id(user_id)}/profile-picture"


async def get_my_profile(user_id: str) -> dict:
    doc = await get_collection(COLLECTION).find_one(
        {"_id": to_object_id(user_id)},
        {
            "_id": 1,
            "name": 1,
            "email": 1,
            "phoneNumber": 1,
            "phone": 1,
            "branch": 1,
            "role": 1,
            "accessLevel": 1,
            "status": 1,
            "createdAt": 1,
            "updatedAt": 1,
            "systemAccount": 1,
        },
    )
    if not doc or doc.get("systemAccount") == UNKNOWN_MARKER:
        raise NotFoundException("User not found")

    picture_path = _profile_picture_path(user_id)
    employee = await get_collection("employees").find_one(
        {"userId": str(doc["_id"])},
        {"branch": 1},
    )
    profile = serialize_doc(doc)
    profile.pop("systemAccount", None)
    profile.pop("password", None)
    profile.pop("passwordEncrypted", None)
    profile["phoneNumber"] = doc.get("phoneNumber") or doc.get("phone")
    profile["branch"] = doc.get("branch") or (employee or {}).get("branch")
    profile.setdefault("name", "")
    profile.setdefault("email", "")
    profile.setdefault("role", UserRole.EMPLOYEE.value)
    profile.setdefault("accessLevel", AdminAccessLevel.FULL.value)
    profile.setdefault("status", "active")
    profile["profilePictureUrl"] = (
        "/users/me/profile-picture" if picture_path.is_file() else None
    )
    return profile


async def save_profile_picture(user_id: str, contents: bytes) -> None:
    user_oid = to_object_id(user_id)
    users = get_collection(COLLECTION)
    user = await users.find_one(
        {"_id": user_oid},
        {"systemAccount": 1},
    )
    if not user or user.get("systemAccount") == UNKNOWN_MARKER:
        raise NotFoundException("User not found")
    if len(contents) > PROFILE_PICTURE_MAX_BYTES:
        raise BadRequestException("Profile picture must be 5 MB or smaller")
    if not _profile_picture_media_type(contents):
        raise BadRequestException("Profile picture must be a JPEG, PNG, or WebP image")

    storage_dir = settings.profile_picture_storage_path
    storage_dir.mkdir(parents=True, exist_ok=True)
    destination = storage_dir / str(user_oid)
    temporary_path = storage_dir / f".{user_oid}.{uuid4().hex}.tmp"
    try:
        temporary_path.write_bytes(contents)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


async def remove_profile_picture(user_id: str) -> None:
    user = await get_collection(COLLECTION).find_one(
        {"_id": to_object_id(user_id)},
        {"systemAccount": 1},
    )
    if not user or user.get("systemAccount") == UNKNOWN_MARKER:
        raise NotFoundException("User not found")

    picture_path = _profile_picture_path(user_id)
    if picture_path.is_file():
        picture_path.unlink()


def get_profile_picture(user_id: str) -> tuple[Path, str]:
    path = _profile_picture_path(user_id)
    if not path.is_file():
        raise NotFoundException("Profile picture not found")
    with path.open("rb") as picture_file:
        media_type = _profile_picture_media_type(picture_file.read(12))
    if not media_type:
        raise BadRequestException("Stored profile picture has an unsupported format")
    return path, media_type


async def get_user_profile_picture(user_id: str) -> tuple[Path, str]:
    user_oid = to_object_id(user_id)
    user = await get_collection(COLLECTION).find_one(
        {"_id": user_oid},
        {"systemAccount": 1},
    )
    if not user or user.get("systemAccount") == UNKNOWN_MARKER:
        raise NotFoundException("User not found")

    return get_profile_picture(user_id)


async def create_user(payload: UserCreate, current_user: CurrentUser | None = None) -> dict:
    users = get_collection(COLLECTION)
    existing = await users.find_one({"email": payload.email})
    if existing:
        raise ConflictException("A user with this email already exists")

    if payload.role == UserRole.ADMIN and current_user and current_user.role != "super_admin":
        # Only super_admin can create another admin
        raise ForbiddenException("Only super admins can create admin users")

    assigned_to_admin = payload.assignedToAdmin
    if current_user and current_user.role == "admin":
        from app.employees.service import get_employee_by_user_id
        admin_employee = await get_employee_by_user_id(current_user.user_id)
        assigned_to_admin = admin_employee["id"]

    access_level = payload.accessLevel.value
    if payload.role != UserRole.ADMIN:
        access_level = AdminAccessLevel.FULL.value

    if current_user and current_user.role == "admin":
        from app.employees.service import get_employee_by_user_id
        admin_employee = await get_employee_by_user_id(current_user.user_id)
        admin_branch = admin_employee.get("branch")
        if not admin_branch:
            admin_u = await users.find_one({"_id": to_object_id(current_user.user_id)}, {"branch": 1})
            admin_branch = (admin_u or {}).get("branch")
        # Force the created user into the admin's branch
        if admin_branch:
            payload.branch = admin_branch

    doc = build_user_document(
        name=payload.name,
        email=str(payload.email),
        phone_number=str(payload.phoneNumber).strip() if payload.phoneNumber else None,
        access_level=access_level,
        hashed_password=hash_password(payload.password),
        role=UserRole(payload.role),
        encrypted_password=encrypt_password(payload.password),
        branch=payload.branch,
        status=payload.status,
    )
    result = await users.insert_one(doc)
    created = await users.find_one({"_id": result.inserted_id})

    # Auto-create employee document for admins and employees
    if created["role"] in (UserRole.ADMIN.value, UserRole.EMPLOYEE.value):
        from app.employees.model import build_employee_document
        emp_doc = build_employee_document(
            user_id=str(created["_id"]),
            branch=payload.branch,
            assigned_to_admin=assigned_to_admin
        )
        employees = get_collection("employees")
        await employees.insert_one(emp_doc)

    return serialize_user(created)


async def create_initial_super_admin(payload: UserCreate) -> dict:
    users = get_collection(COLLECTION)
    existing_super_admin = await users.find_one({"role": UserRole.SUPER_ADMIN.value})
    if existing_super_admin:
        raise ConflictException("A super admin user already exists")

    super_admin_payload = UserCreate(
        name=payload.name,
        email=payload.email,
        phoneNumber=payload.phoneNumber,
        accessLevel=payload.accessLevel,
        password=payload.password,
        role=UserRole.SUPER_ADMIN,
        branch=payload.branch,
        status=payload.status,
    )
    return await create_user(super_admin_payload)


async def create_initial_admin(payload: UserCreate) -> dict:
    users = get_collection(COLLECTION)
    existing_admin = await users.find_one({"role": UserRole.ADMIN.value})
    if existing_admin:
        raise ConflictException("An admin user already exists")

    admin_payload = UserCreate(
        name=payload.name,
        email=payload.email,
        password=payload.password,
        role=UserRole.ADMIN,
        branch=payload.branch,
        status=payload.status,
    )
    return await create_user(admin_payload)


async def get_user_by_email(email: str) -> dict | None:
    users = get_collection(COLLECTION)
    doc = await users.find_one({"email": email})
    return doc  # raw doc kept internally (includes hashed password) for auth checks


async def get_user_by_id(user_id: str) -> dict:
    users = get_collection(COLLECTION)
    doc = await users.find_one({"_id": to_object_id(user_id)})
    if not doc or doc.get("systemAccount") == UNKNOWN_MARKER:
        raise NotFoundException("User not found")
    return serialize_user(doc)


async def list_users(current_user: CurrentUser) -> list[dict]:
    users_col = get_collection(COLLECTION)
    employees_col = get_collection("employees")
    email_master_col = get_collection("email_master")
    profiles_col = get_collection("profiles")
    campaigns_col = get_collection("campaigns")
    profile_emails_col = get_collection("profile_emails")

    query = {"systemAccount": {"$ne": UNKNOWN_MARKER}}
    if current_user.role == "admin":
        from app.employees.service import get_employee_by_user_id
        try:
            admin_emp = await get_employee_by_user_id(current_user.user_id)
            admin_emp_id = str(admin_emp.get("id"))

            if current_user.access_level == "partial":
                # Partial admin: find employees assigned to this admin
                assigned_emps = [e async for e in employees_col.find({"assignedToAdmin": admin_emp_id})]
                allowed_user_ids = [
                    str(employee["userId"])
                    for employee in assigned_emps
                    if employee.get("userId")
                ]
            else:
                # Full admin: find all employees and users in the same branch.
                # Branch may be on the employee doc or only on the user doc — check both.
                admin_branch = admin_emp.get("branch")
                if not admin_branch:
                    admin_user_doc = await users_col.find_one(
                        {"_id": to_object_id(current_user.user_id)}, {"branch": 1}
                    )
                    admin_branch = (admin_user_doc or {}).get("branch")
                if admin_branch:
                    import re
                    branch_regex = {"$regex": f"^{re.escape(str(admin_branch).strip())}$", "$options": "i"}
                    # Only include users whose role is 'employee' in this branch
                    branch_user_docs = [
                        u async for u in users_col.find(
                            {"branch": branch_regex, "role": "employee"},
                            {"_id": 1}
                        )
                    ]
                    allowed_user_ids = [str(u["_id"]) for u in branch_user_docs]
                else:
                    allowed_user_ids = []

            # Always allow admin to see themselves
            allowed_user_ids.append(current_user.user_id)
            query = {"_id": {"$in": [to_object_id(uid) for uid in set(allowed_user_ids)]}}
        except Exception:
            # If admin has no employee document or error, they only see themselves
            query = {"_id": to_object_id(current_user.user_id)}
    elif current_user.role == "employee":
        query = {"_id": to_object_id(current_user.user_id)}

    # ── 1. Fetch scoped users ────────────────────────────────────────────────────
    docs = [d async for d in users_col.find(query)]
    docs = [doc for doc in docs if doc.get("systemAccount") != UNKNOWN_MARKER]
    users = serialize_list_users_with_password(docs)
    for user in users:
        user["profilePictureUrl"] = _profile_picture_url(user["id"])
    user_ids = [u["id"] for u in users]

    if not user_ids:
        return users

    # ── 2. Build user_id → employee map ───────────────────────────────────────
    # profiles and campaigns store employees._id (not users._id)
    emp_docs = [d async for d in employees_col.find({"userId": {"$in": user_ids}}, {"_id": 1, "userId": 1, "assignedToAdmin": 1})]
    user_to_emp = {str(e["userId"]): str(e["_id"]) for e in emp_docs}
    user_to_admin = {str(e["userId"]): str(e.get("assignedToAdmin", "")) for e in emp_docs}
    emp_ids = list(user_to_emp.values())

    # ── 3. Count unique emails in email_master per user ───────────────────────
    email_agg = await email_master_col.aggregate([
        {"$match": {"uploadedBy": {"$in": user_ids}, "isDuplicate": False}},
        {"$group": {"_id": "$uploadedBy", "uniqueUploads": {"$sum": 1}}}
    ]).to_list(None)
    email_map = {r["_id"]: r["uniqueUploads"] for r in email_agg}

    # ── 4. Batch: profile count per employee_id ───────────────────────────────
    profile_agg = await profiles_col.aggregate([
        {"$match": {"employeeId": {"$in": emp_ids}}},
        {"$group": {"_id": "$employeeId", "count": {"$sum": 1}}}
    ]).to_list(None)
    profile_map = {r["_id"]: r["count"] for r in profile_agg}

    # ── 5. Batch: campaign stats per employee_id ──────────────────────────────
    running_statuses = _get_running_campaign_statuses()
    pending_statuses = _get_pending_campaign_statuses()
    campaign_agg = await campaigns_col.aggregate([
        {"$match": {"employeeId": {"$in": emp_ids}}},
        {"$group": {
            "_id": "$employeeId",
            "totalCampaigns": {"$sum": 1},
            "runningCampaigns": {"$sum": {
                "$cond": [{"$in": ["$status", running_statuses]}, 1, 0]
            }},
            "pendingCampaigns": {"$sum": {
                "$cond": [{"$in": ["$status", pending_statuses]}, 1, 0]
            }}
        }}
    ]).to_list(None)
    campaign_map = {r["_id"]: r for r in campaign_agg}

    # ── 6. Batch: pending profile-email count per employee_id ─────────────────
    pending_emails_agg = await profile_emails_col.aggregate([
        {"$match": {"employeeId": {"$in": emp_ids}, "sendStatus": {"$in": ["pending", "failed", "paused", "sending"]}}},
        {"$group": {"_id": "$employeeId", "count": {"$sum": 1}}}
    ]).to_list(None)
    pending_emails_map = {r["_id"]: r["count"] for r in pending_emails_agg}

    # ── 7. Merge stats into each user (translate user_id → emp_id for lookup) ─
    for u in users:
        uid = u["id"]
        eid = user_to_emp.get(uid)          # employee doc id for this user
        admin_id = user_to_admin.get(uid, "")
        stat_employee_ids = (
            unknown_employee_ids
            if uid == UNKNOWN_USER_ID
            else ([eid] if eid else [])
        )
        total_campaigns = sum(campaign_map.get(stat_id, {}).get("totalCampaigns", 0) for stat_id in stat_employee_ids)
        running_campaigns = sum(campaign_map.get(stat_id, {}).get("runningCampaigns", 0) for stat_id in stat_employee_ids)
        pending_campaigns = sum(campaign_map.get(stat_id, {}).get("pendingCampaigns", 0) for stat_id in stat_employee_ids)
        u["employeeId"] = eid
        u["assignedToAdmin"] = admin_id
        u["stats"] = {
            "uniqueUploads": email_map.get(uid, 0),
            "totalProfiles": sum(profile_map.get(stat_id, 0) for stat_id in stat_employee_ids),
            "totalCampaigns": total_campaigns,
            "runningCampaigns": running_campaigns,
            "pendingEmails": sum(pending_emails_map.get(stat_id, 0) for stat_id in stat_employee_ids),
            "pendingCampaigns": pending_campaigns,
        }

    return users





async def update_user(user_id: str, payload: UserUpdate, current_user: CurrentUser) -> dict:
    users = get_collection(COLLECTION)
    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    target = await users.find_one({"_id": to_object_id(user_id)}, {"role": 1, "systemAccount": 1})
    if not target:
        raise NotFoundException("User not found")
    if target.get("systemAccount") == UNKNOWN_MARKER:
        raise ForbiddenException("The Unknown system account cannot be modified")
    if current_user.role == "employee":
        if str(target["_id"]) != current_user.user_id:
            raise ForbiddenException("You can only access your own account")
        if update_data:
            raise ForbiddenException("Employee account details are read-only")

    if "accessLevel" in update_data or "role" in update_data:
        requested_role = update_data.get("role", target.get("role"))
        if isinstance(requested_role, UserRole):
            requested_role = requested_role.value
        if "accessLevel" in update_data and requested_role != UserRole.ADMIN.value:
            raise ForbiddenException("Access level can only be changed for admin users")
        if "accessLevel" in update_data and current_user.role != "super_admin":
            raise ForbiddenException(
                "Only super admins can change admin access levels"
            )
        if "accessLevel" in update_data:
            update_data["accessLevel"] = update_data["accessLevel"].value
        if "role" in update_data:
            if current_user.role != "super_admin":
                raise ForbiddenException("Only super admins can change user roles")
            update_data["role"] = update_data["role"].value
            if (
                update_data["role"] == UserRole.ADMIN.value
                and "accessLevel" not in update_data
            ):
                update_data["accessLevel"] = AdminAccessLevel.FULL.value

    if "phoneNumber" in update_data:
        update_data["phoneNumber"] = update_data["phoneNumber"].strip()

    if current_user.role == "admin":
        if current_user.access_level == "partial":
            if user_id != current_user.user_id:
                raise ForbiddenException(
                    "Partial-access admins cannot modify assigned employee data"
                )
        else:
            # Full admin: check target user
            target_user = await users.find_one({"_id": to_object_id(user_id)})
            if not target_user:
                raise NotFoundException("User not found")
            # Cannot modify other admins or super admins
            if user_id != current_user.user_id and target_user.get("role") in {"admin", "super_admin"}:
                raise ForbiddenException("Admins cannot modify other admins or super admins")
            # Must belong to same branch
            from app.employees.service import get_employee_by_user_id
            admin_emp = await get_employee_by_user_id(current_user.user_id)
            admin_branch = admin_emp.get("branch")
            if not admin_branch:
                admin_u = await users.find_one({"_id": to_object_id(current_user.user_id)}, {"branch": 1})
                admin_branch = (admin_u or {}).get("branch")
            target_branch = target_user.get("branch")
            if (
                admin_branch
                and target_branch
                and str(admin_branch).strip().casefold() != str(target_branch).strip().casefold()
            ):
                raise ForbiddenException("You cannot modify users outside your branch")
            # Prevent changing branch to something else
            if "branch" in update_data and admin_branch:
                update_data["branch"] = admin_branch

    # Extract employee-specific fields
    assigned_to_admin = update_data.pop("assignedToAdmin", None)
    branch = update_data.get("branch", None)
    if "role" in update_data and update_data["role"] != UserRole.EMPLOYEE.value:
        assigned_to_admin = None

    if not update_data and assigned_to_admin is None:
        return await get_user_by_id(user_id)

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    if target and "role" in update_data and target.get("role") != update_data["role"]:
        employees = get_collection("employees")
        employee = await employees.find_one(
            {"userId": str(target["_id"])}, {"_id": 1}
        )
        employee_id = employee.get("_id") if employee else None

        # Remove subordinate links before an admin loses the admin role.
        if (
            target.get("role") == UserRole.ADMIN.value
            and update_data["role"] != UserRole.ADMIN.value
            and employee_id
        ):
            await employees.update_many(
                {"assignedToAdmin": {"$in": [str(employee_id), employee_id]}},
                {"$set": {"assignedToAdmin": None, "updatedAt": now}},
            )

        # A user promoted out of the employee role must not retain an admin assignment.
        if update_data["role"] != UserRole.EMPLOYEE.value and employee_id:
            await employees.update_one(
                {"_id": employee_id},
                {"$set": {"assignedToAdmin": None, "updatedAt": now}},
            )

    if update_data:
        update_data["updatedAt"] = now
        result = await users.find_one_and_update(
            {"_id": to_object_id(user_id)}, {"$set": update_data}, return_document=True
        )
        if not result:
            raise NotFoundException("User not found")
    else:
        result = await users.find_one({"_id": to_object_id(user_id)})
        if not result:
            raise NotFoundException("User not found")

    # Update employee document if assignedToAdmin or branch is provided
    if assigned_to_admin is not None or branch is not None:
        employees = get_collection("employees")
        emp_update = {"updatedAt": datetime.now(timezone.utc)}
        if branch is not None:
            emp_update["branch"] = branch
        if assigned_to_admin is not None:
            # If empty string, treat as unassign (None)
            emp_update["assignedToAdmin"] = assigned_to_admin if assigned_to_admin else None

        await employees.update_one(
            {"userId": str(result["_id"])},
            {"$set": emp_update}
        )

        if assigned_to_admin is not None:
            employee = await employees.find_one(
                {"userId": str(result["_id"])}, {"_id": 1}
            )
            if employee:
                from app.profiles.service import _resolve_admin_name

                profiles = get_collection("profiles")
                admin_name = await _resolve_admin_name(assigned_to_admin or "")
                await profiles.update_many(
                    {"employeeId": str(employee["_id"])},
                    {"$set": {"assignedAdmin": admin_name}},
                )

    return serialize_user(result)


async def delete_user(
    user_id: str,
    actor_role: str | None = None,
    actor_id: str | None = None,
) -> None:
    users = get_collection(COLLECTION)
    employees = get_collection("employees")
    user = await users.find_one(
        {"_id": to_object_id(user_id)},
        {"name": 1, "email": 1, "role": 1, "branch": 1, "systemAccount": 1},
    )
    if not user:
        raise NotFoundException("User not found")
    if user.get("systemAccount") == UNKNOWN_MARKER:
        raise ForbiddenException("The Unknown system account cannot be deleted")

    if actor_role == "admin":
        is_self = actor_id and str(user["_id"]) == actor_id
        if not is_self and user.get("role") in {"admin", "super_admin"}:
            raise ForbiddenException("Admins cannot delete other admins or super admins")

        # Ensure target is in same branch
        if not is_self and actor_id:
            from app.employees.service import get_employee_by_user_id
            admin_emp = await get_employee_by_user_id(actor_id)
            admin_branch = admin_emp.get("branch")
            if not admin_branch:
                admin_u = await users.find_one({"_id": to_object_id(actor_id)}, {"branch": 1})
                admin_branch = (admin_u or {}).get("branch")
            target_branch = user.get("branch")
            if (
                admin_branch
                and target_branch
                and str(admin_branch).strip().casefold() != str(target_branch).strip().casefold()
            ):
                raise ForbiddenException("You cannot delete users outside your branch")

    employee = await employees.find_one(
        {"userId": user_id},
        {"_id": 1, "userId": 1, "branch": 1, "assignedToAdmin": 1},
    )
    employee_id = str(employee["_id"]) if employee else None
    deleted_name = user.get("name") or user.get("email") or "Unknown"
    if employee_id is None:
        from app.users.unknown import find_legacy_employee_id_for_user

        employee_id = await find_legacy_employee_id_for_user(user_id, deleted_name)

    if actor_role in {"admin", "super_admin"}:
        # Notify while the employee assignment still exists so admins receive the event.
        try:
            from app.notifications.schema import NotificationType
            from app.notifications.service import create_notification

            notification_target = str(employee["_id"]) if employee else user_id
            display_name = user.get("name") or user.get("email") or user_id
            await create_notification(
                notification_target,
                f"User {display_name} was deleted.",
                NotificationType.INFO,
            )
        except Exception:
            # Deletion must not fail if notification delivery/storage is unavailable.
            pass

    await preserve_deleted_user_data(
        user_id=user_id,
        employee_id=employee_id,
        deleted_name=deleted_name,
        branch=(employee or {}).get("branch") or user.get("branch"),
        assigned_to_admin=(employee or {}).get("assignedToAdmin"),
    )

    if employee_id:
        await employees.update_many(
            {"assignedToAdmin": employee_id},
            {"$set": {"assignedToAdmin": None, "updatedAt": datetime.now(timezone.utc)}},
        )

    result = await users.delete_one({"_id": to_object_id(user_id)})
    if result.deleted_count == 0:
        raise NotFoundException("User not found")

    # Cascade delete the employee record to prevent orphans
    await employees.delete_many({"userId": user_id})


async def update_password(
    user_id: str,
    payload: PasswordUpdate,
    current_user: CurrentUser,
) -> dict:
    users, user_doc = await _get_authorized_password_target(user_id, current_user)
    if user_id == current_user.user_id:
        if not payload.old_password:
            raise BadRequestException("Old password is required")
        if not verify_password(payload.old_password, user_doc.get("password", "")):
            raise BadRequestException("Old password is incorrect")

    return await _save_user_password(users, user_id, payload.new_password)


async def _get_authorized_password_target(
    user_id: str,
    current_user: CurrentUser,
):
    if current_user.role == "employee":
        raise ForbiddenException("Employees cannot change their password")
    if current_user.role not in {"admin", "super_admin"}:
        raise ForbiddenException("Admin access is required to change passwords")

    users = get_collection(COLLECTION)
    target_id = to_object_id(user_id)
    user_doc = await users.find_one({"_id": target_id})
    if not user_doc:
        raise NotFoundException("User not found")
    if user_doc.get("systemAccount") == UNKNOWN_MARKER:
        raise ForbiddenException("The Unknown system account cannot be modified")

    if user_id == current_user.user_id or current_user.role == "super_admin":
        return users, user_doc

    if current_user.access_level != "full":
        raise ForbiddenException("Full access is required to change employee passwords")
    if user_doc.get("role") != "employee":
        raise ForbiddenException("Admins can only change passwords for branch employees")

    employees = get_collection("employees")
    admin_employee = await employees.find_one({"userId": current_user.user_id})
    target_employee = await employees.find_one({"userId": user_id})
    admin_user = await users.find_one(
        {"_id": to_object_id(current_user.user_id)},
        {"branch": 1},
    )
    admin_branch = (
        (admin_employee or {}).get("branch")
        or (admin_user or {}).get("branch")
        or ""
    )
    target_branch = (
        (target_employee or {}).get("branch")
        or user_doc.get("branch")
        or ""
    )
    if (
        not admin_branch
        or not target_branch
        or str(admin_branch).strip().casefold()
        != str(target_branch).strip().casefold()
    ):
        raise ForbiddenException("You can only change passwords for employees in your branch")

    return users, user_doc


async def _save_user_password(users, user_id: str, new_password: str) -> dict:
    result = await users.find_one_and_update(
        {"_id": to_object_id(user_id)},
        {
            "$set": {
                "password": hash_password(new_password),
                "passwordEncrypted": encrypt_password(new_password),
                "updatedAt": datetime.now(timezone.utc),
            },
        },
        return_document=True,
    )
    if not result:
        raise NotFoundException("User not found")
    return serialize_user(result)


async def reset_user_password(
    user_id: str,
    new_password: str,
    current_user: CurrentUser,
) -> dict:
    users, _ = await _get_authorized_password_target(user_id, current_user)
    return await _save_user_password(users, user_id, new_password)


async def migrate_add_branch() -> dict:
    """Add branch 'Vellore' to all users that don't have it"""
    from datetime import datetime, timezone

    users = get_collection(COLLECTION)
    result = await users.update_many(
        {"branch": {"$exists": False}},
        {
            "$set": {
                "branch": "Vellore",
                "updatedAt": datetime.now(timezone.utc)
            }
        }
    )

    return {
        "matched_count": result.matched_count,
        "modified_count": result.modified_count,
        "message": f"Updated {result.modified_count} users with branch 'Vellore'"
    }


async def _resolve_employee_id_for_user(user_id: str) -> str | None:
    """Resolve the employee document for a user so stats use employeeId consistently."""
    employees = get_collection("employees")
    employee_doc = await employees.find_one({"userId": user_id})
    if not employee_doc:
        return None
    return str(employee_doc.get("_id"))


def _get_running_campaign_statuses() -> list[str]:
    """Return the active campaign statuses that should count as running."""
    from app.campaigns.model import CampaignStatus

    return [CampaignStatus.RUNNING.value, CampaignStatus.PROCESSING.value]


def _get_pending_campaign_statuses() -> list[str]:
    """Return campaign statuses that should count as pending."""
    from app.campaigns.model import CampaignStatus

    return [
        CampaignStatus.PENDING.value,
        CampaignStatus.SCHEDULED.value,
        CampaignStatus.RESCHEDULED.value,
        CampaignStatus.WAITING_FOR_MAILS.value,
        CampaignStatus.FAILED.value,
        CampaignStatus.PAUSED.value,
    ]


async def get_user_details(
    user_id: str,
    current_user: CurrentUser | None = None,
) -> dict:
    """Get full user profile including performance stats: uploads, profiles, campaigns, running campaigns."""
    users = get_collection(COLLECTION)
    logs_col = get_collection("logs")
    profiles_col = get_collection("profiles")
    campaigns_col = get_collection("campaigns")

    doc = await users.find_one({"_id": to_object_id(user_id)})
    if not doc or doc.get("systemAccount") == UNKNOWN_MARKER:
        raise NotFoundException("User not found")

    user = serialize_user(doc)
    employee_id = await _resolve_employee_id_for_user(user_id)
    if user_id == UNKNOWN_USER_ID:
        if current_user and current_user.role == "admin":
            from app.core.dependencies import resolve_employee_context

            employee_ids, _ = await resolve_employee_context(
                current_user,
                UNKNOWN_EMPLOYEE_ID,
            )
        else:
            from app.users.unknown import resolve_unknown_employee_ids

            employee_ids = await resolve_unknown_employee_ids()
    else:
        employee_ids = [employee_id or user_id]

    # ── Upload stats from logs ─────────────────────────────────────────────
    upload_match = {"action": "UPLOAD", "employeeId": {"$in": employee_ids}}

    upload_pipeline = [
        {"$match": upload_match},
        {
            "$group": {
                "_id": None,
                "totalUploads": {"$sum": "$uploadedCount"},
                "totalUnique": {"$sum": "$uniqueCount"},
                "totalDuplicate": {"$sum": "$duplicateCount"},
                "uploadCount": {"$sum": 1},
            }
        }
    ]
    upload_agg = await logs_col.aggregate(upload_pipeline).to_list(1)
    upload_stats = upload_agg[0] if upload_agg else {}
    total_uploads = upload_stats.get("totalUploads", 0)
    total_unique = upload_stats.get("totalUnique", 0)
    total_duplicate = upload_stats.get("totalDuplicate", 0)
    total_invalid = max(0, total_uploads - total_unique - total_duplicate)
    upload_events = upload_stats.get("uploadCount", 0)

    # ── Profile count ─────────────────────────────────────────────────────
    total_profiles = await profiles_col.count_documents(
        {"employeeId": {"$in": employee_ids}}
    )

    # ── Campaign stats ────────────────────────────────────────────────────
    running_statuses = _get_running_campaign_statuses()

    total_campaigns = await campaigns_col.count_documents(
        {"employeeId": {"$in": employee_ids}}
    )
    running_campaigns = await campaigns_col.count_documents(
        {
            "employeeId": {"$in": employee_ids},
            "status": {"$in": running_statuses},
        }
    )

    # ── Recent upload history (last 10 batches) ────────────────────────────
    recent_query = {"action": "UPLOAD", "employeeId": {"$in": employee_ids}}

    recent_cursor = logs_col.find(
        recent_query,
        {"_id": 0, "runDate": 1, "uploadedCount": 1, "uniqueCount": 1, "duplicateCount": 1}
    ).sort("runDate", -1).limit(10)
    recent_uploads = [d async for d in recent_cursor]

    return {
        **user,
        "stats": {
            "totalUploads": total_uploads,
            "totalUnique": total_unique,
            "totalDuplicate": total_duplicate,
            "totalInvalid": total_invalid,
            "uploadEvents": upload_events,
            "totalProfiles": total_profiles,
            "totalCampaigns": total_campaigns,
            "runningCampaigns": running_campaigns,
        },
        "recentUploads": recent_uploads,
    }
