from app.core.exceptions import ConflictException, NotFoundException
from app.core.security import encrypt_password, hash_password, verify_password
from app.database.mongodb import get_collection
from app.users.model import UserRole, build_user_document
from app.users.schema import UserCreate, UserUpdate, PasswordUpdate
from app.utils.response import serialize_doc, serialize_user_with_password, serialize_list_users_with_password, to_object_id

COLLECTION = "users"


async def create_user(payload: UserCreate) -> dict:
    users = get_collection(COLLECTION)
    existing = await users.find_one({"email": payload.email})
    if existing:
        raise ConflictException("A user with this email already exists")

    doc = build_user_document(
        name=payload.name,
        email=str(payload.email),
        hashed_password=hash_password(payload.password),
        role=UserRole(payload.role),
        encrypted_password=encrypt_password(payload.password),
        branch=payload.branch,
        status=payload.status,
    )
    result = await users.insert_one(doc)
    created = await users.find_one({"_id": result.inserted_id})
    return serialize_user_with_password(created)


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
    )
    return await create_user(admin_payload)


async def get_user_by_email(email: str) -> dict | None:
    users = get_collection(COLLECTION)
    doc = await users.find_one({"email": email})
    return doc  # raw doc kept internally (includes hashed password) for auth checks


async def get_user_by_id(user_id: str) -> dict:
    users = get_collection(COLLECTION)
    doc = await users.find_one({"_id": to_object_id(user_id)})
    if not doc:
        raise NotFoundException("User not found")
    return serialize_user_with_password(doc)


async def list_users() -> list[dict]:
    users_col = get_collection(COLLECTION)
    employees_col = get_collection("employees")
    email_master_col = get_collection("email_master")
    profiles_col = get_collection("profiles")
    campaigns_col = get_collection("campaigns")

    # ── 1. Fetch all users ────────────────────────────────────────────────────
    docs = [d async for d in users_col.find({})]
    users = serialize_list_users_with_password(docs)
    user_ids = [u["id"] for u in users]

    if not user_ids:
        return users

    # ── 2. Build user_id → employee_id map ────────────────────────────────────
    # profiles and campaigns store employees._id (not users._id)
    emp_docs = [d async for d in employees_col.find({"userId": {"$in": user_ids}}, {"_id": 1, "userId": 1})]
    user_to_emp = {str(e["userId"]): str(e["_id"]) for e in emp_docs}
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
    campaign_agg = await campaigns_col.aggregate([
        {"$match": {"employeeId": {"$in": emp_ids}}},
        {"$group": {
            "_id": "$employeeId",
            "totalCampaigns": {"$sum": 1},
            "runningCampaigns": {"$sum": {
                "$cond": [{"$in": ["$status", ["running", "scheduled"]]}, 1, 0]
            }}
        }}
    ]).to_list(None)
    campaign_map = {r["_id"]: r for r in campaign_agg}

    # ── 6. Merge stats into each user (translate user_id → emp_id for lookup) ─
    for u in users:
        uid = u["id"]
        eid = user_to_emp.get(uid)          # employee doc id for this user
        cm = campaign_map.get(eid, {}) if eid else {}
        u["stats"] = {
            "uniqueUploads": email_map.get(uid, 0),
            "totalProfiles": profile_map.get(eid, 0) if eid else 0,
            "totalCampaigns": cm.get("totalCampaigns", 0),
            "runningCampaigns": cm.get("runningCampaigns", 0),
        }

    return users





async def update_user(user_id: str, payload: UserUpdate) -> dict:
    users = get_collection(COLLECTION)
    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        return await get_user_by_id(user_id)

    from datetime import datetime, timezone

    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = await users.find_one_and_update(
        {"_id": to_object_id(user_id)}, {"$set": update_data}, return_document=True
    )
    if not result:
        raise NotFoundException("User not found")
    return serialize_user_with_password(result)


async def delete_user(user_id: str) -> None:
    users = get_collection(COLLECTION)
    result = await users.delete_one({"_id": to_object_id(user_id)})
    if result.deleted_count == 0:
        raise NotFoundException("User not found")


async def update_password(user_id: str, payload: PasswordUpdate) -> dict:
    from app.core.exceptions import BadRequestException
    from datetime import datetime, timezone
    
    users = get_collection(COLLECTION)
    user_doc = await users.find_one({"_id": to_object_id(user_id)})
    if not user_doc:
        raise NotFoundException("User not found")
    
    # Verify old password
    if not verify_password(payload.old_password, user_doc.get("password", "")):
        raise BadRequestException("Old password is incorrect")
    
    # Hash and encrypt new password
    hashed = hash_password(payload.new_password)
    encrypted = encrypt_password(payload.new_password)
    
    # Update password
    result = await users.find_one_and_update(
        {"_id": to_object_id(user_id)},
        {
            "$set": {
                "password": hashed,
                "passwordEncrypted": encrypted,
                "updatedAt": datetime.now(timezone.utc)
            }
        },
        return_document=True
    )
    
    return serialize_user_with_password(result)


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


async def get_user_details(user_id: str) -> dict:
    """Get full user profile including performance stats: uploads, profiles, campaigns, running campaigns."""
    from datetime import datetime, timezone

    users = get_collection(COLLECTION)
    logs_col = get_collection("logs")
    profiles_col = get_collection("profiles")
    campaigns_col = get_collection("campaigns")

    doc = await users.find_one({"_id": to_object_id(user_id)})
    if not doc:
        raise NotFoundException("User not found")

    user = serialize_user_with_password(doc)

    # ── Upload stats from logs ─────────────────────────────────────────────
    upload_pipeline = [
        {"$match": {"employeeId": user_id, "action": "UPLOAD"}},
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
    total_profiles = await profiles_col.count_documents({"employeeId": user_id})

    # ── Campaign stats ────────────────────────────────────────────────────
    total_campaigns = await campaigns_col.count_documents({"employeeId": user_id})
    running_campaigns = await campaigns_col.count_documents(
        {"employeeId": user_id, "status": {"$in": ["running", "scheduled"]}}
    )

    # ── Recent upload history (last 10 batches) ────────────────────────────
    recent_cursor = logs_col.find(
        {"employeeId": user_id, "action": "UPLOAD"},
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
