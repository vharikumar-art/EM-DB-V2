from datetime import datetime, timezone

from app.core.exceptions import ConflictException, NotFoundException
from app.core.security import decrypt_password
from app.database.mongodb import get_collection
from app.employees.model import build_employee_document
from app.employees.schema import EmployeeCreate, EmployeeUpdate
from app.users.model import UserRole
from app.users.service import create_user
from app.users.schema import UserCreate
from app.utils.response import serialize_doc, to_object_id

COLLECTION = "employees"


async def create_employee(payload: EmployeeCreate) -> dict:
    employees = get_collection(COLLECTION)

    # Create the underlying auth user first.
    user = await create_user(
        UserCreate(
            name=payload.name,
            email=payload.email,
            password=payload.password,
            role=payload.role,
        )
    )

    try:
        doc = build_employee_document(
            user_id=user["id"],
            branch=payload.branch,
        )

        result = await employees.insert_one(doc)
        created = await employees.find_one({"_id": result.inserted_id})
        employee_out = serialize_doc(created)
        employee_out["name"] = user["name"]
        employee_out["email"] = user["email"]
        return employee_out
    except Exception:
        # Roll back the user record if employee creation fails, to avoid orphan accounts.
        users = get_collection("users")
        await users.delete_one({"_id": to_object_id(user["id"])})
        raise


async def _attach_user_info(employee_doc: dict, include_password: bool = False) -> dict:
    users = get_collection("users")
    user = await users.find_one({"_id": to_object_id(employee_doc["userId"])})
    employee_doc["name"] = user["name"] if user else None
    employee_doc["email"] = user["email"] if user else None
    employee_doc["userStatus"] = user["status"] if user else None
    if include_password and user and user.get("passwordEncrypted"):
        employee_doc["password"] = decrypt_password(user["passwordEncrypted"])
    return employee_doc


async def list_employees() -> list[dict]:
    employees = get_collection(COLLECTION)
    cursor = employees.find({})
    docs = [serialize_doc(d) async for d in cursor]
    # include_password=True so the frontend Accounts table can display it
    return [await _attach_user_info(d, include_password=True) for d in docs]



async def get_employee(employee_id: str) -> dict:
    employees = get_collection(COLLECTION)
    doc = await employees.find_one({"_id": to_object_id(employee_id)})
    if not doc:
        raise NotFoundException("Employee not found")
    return await _attach_user_info(serialize_doc(doc), include_password=True)


async def get_employee_by_user_id(user_id: str) -> dict:
    employees = get_collection(COLLECTION)
    doc = await employees.find_one({"userId": user_id})
    if not doc:
        raise NotFoundException("Employee record not found for this user")
    return await _attach_user_info(serialize_doc(doc))


async def update_employee(employee_id: str, payload: EmployeeUpdate) -> dict:
    employees = get_collection(COLLECTION)
    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        return await get_employee(employee_id)

    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = await employees.find_one_and_update(
        {"_id": to_object_id(employee_id)}, {"$set": update_data}, return_document=True
    )
    if not result:
        raise NotFoundException("Employee not found")
    return await _attach_user_info(serialize_doc(result))


async def delete_employee(employee_id: str) -> None:
    employees = get_collection(COLLECTION)
    result = await employees.delete_one({"_id": to_object_id(employee_id)})
    if result.deleted_count == 0:
        raise NotFoundException("Employee not found")
