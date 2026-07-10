from app.core.exceptions import ConflictException, NotFoundException
from app.core.security import encrypt_password, hash_password
from app.database.mongodb import get_collection
from app.users.model import UserRole, build_user_document
from app.users.schema import UserCreate, UserUpdate
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
    users = get_collection(COLLECTION)
    cursor = users.find({})
    docs = [d async for d in cursor]
    return serialize_list_users_with_password(docs)


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
