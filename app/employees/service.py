from datetime import datetime, timezone

from app.core.dependencies import CurrentUser
from app.core.exceptions import ConflictException, NotFoundException, ForbiddenException
from app.core.security import decrypt_password
from app.database.mongodb import get_collection
from app.employees.model import build_employee_document
from app.employees.schema import EmployeeCreate, EmployeeUpdate
from app.users.model import UserRole
from app.users.service import create_user
from app.users.schema import UserCreate
from app.utils.response import serialize_doc, to_object_id

COLLECTION = "employees"


async def create_employee(payload: EmployeeCreate, current_user: CurrentUser) -> dict:
    employees = get_collection(COLLECTION)

    assigned_to_admin = payload.assignedToAdmin
    if current_user.role == "admin":
        admin_employee = await get_employee_by_user_id(current_user.user_id)
        # Override branch to admin's branch if not provided or to ensure they are created in the same branch
        if not payload.branch:
            payload.branch = admin_employee.get("branch")

    # Create the underlying auth user first.
    user = await create_user(
        UserCreate(
            name=payload.name,
            email=payload.email,
            password=payload.password,
            role=payload.role,
            assignedToAdmin=assigned_to_admin,
        )
    )

    try:
        created = await employees.find_one({"userId": user["id"]})
        if not created:
            raise NotFoundException("Employee record could not be created")
        employee_out = serialize_doc(created)
        employee_out["name"] = user["name"]
        employee_out["email"] = user["email"]
        return employee_out
    except Exception:
        # Roll back the user record if employee creation fails, to avoid orphan accounts.
        users = get_collection("users")
        await users.delete_one({"_id": to_object_id(user["id"])})
        await employees.delete_one({"userId": user["id"]})
        raise


async def _attach_user_info(employee_doc: dict, include_password: bool = False) -> dict:
    users = get_collection("users")
    user = await users.find_one({"_id": to_object_id(employee_doc["userId"])})
    employee_doc["name"] = user["name"] if user else None
    employee_doc["email"] = user["email"] if user else None
    employee_doc["userStatus"] = user["status"] if user else None
    if not employee_doc.get("branch") and user and user.get("branch"):
        employee_doc["branch"] = user["branch"]
    if include_password and user and user.get("passwordEncrypted"):
        employee_doc["password"] = decrypt_password(user["passwordEncrypted"])
    return employee_doc


async def list_employees(current_user: CurrentUser | None = None) -> list[dict]:
    employees = get_collection(COLLECTION)
    query = {}
    
    if current_user and current_user.role == "admin":
        try:
            admin_emp = await get_employee_by_user_id(current_user.user_id)
            admin_emp_id = str(admin_emp.get("id"))

            if current_user.access_level == "partial":
                query = {"assignedToAdmin": admin_emp_id}
            else:
                admin_branch = admin_emp.get("branch")

                # Branch may only be on the user's document.
                if not admin_branch:
                    users_col = get_collection("users")
                    admin_user_doc = await users_col.find_one(
                        {"_id": to_object_id(current_user.user_id)}, {"branch": 1}
                    )
                    admin_branch = (admin_user_doc or {}).get("branch")

                if admin_branch:
                    import re
                    branch_regex = {
                        "$regex": f"^{re.escape(str(admin_branch).strip())}$",
                        "$options": "i",
                    }
                    users_col = get_collection("users")
                    branch_users = [
                        user async for user in users_col.find(
                            {"branch": branch_regex, "role": "employee"},
                            {"_id": 1},
                        )
                    ]
                    branch_user_ids = [
                        str(user["_id"]) for user in branch_users
                    ] + [user["_id"] for user in branch_users]

                    query = {
                        "$or": [
                            {"_id": to_object_id(admin_emp_id)},
                            {"userId": {"$in": branch_user_ids}},
                        ]
                    }
                else:
                    query = {"_id": to_object_id(admin_emp_id)}
        except Exception:
            # If admin has no employee profile, they should see NO employees, not ALL employees
            query = {"_id": "none"}

    cursor = employees.find(query)
    docs = [serialize_doc(d) async for d in cursor]
    # include_password=True so the frontend Accounts table can display it
    return [await _attach_user_info(d, include_password=True) for d in docs]



async def get_employee(employee_id: str, current_user: CurrentUser | None = None) -> dict:
    employees = get_collection(COLLECTION)
    doc = await employees.find_one({"_id": to_object_id(employee_id)})
    if not doc:
        raise NotFoundException("Employee not found")
        
    if current_user and current_user.role == "admin":
        try:
            admin_emp = await get_employee_by_user_id(current_user.user_id)
            admin_emp_id = str(admin_emp.get("id"))
            admin_branch = admin_emp.get("branch")

            # Fall back to users doc if branch not on employee doc
            if not admin_branch:
                users_col = get_collection("users")
                admin_user_doc = await users_col.find_one(
                    {"_id": to_object_id(current_user.user_id)}, {"branch": 1}
                )
                admin_branch = (admin_user_doc or {}).get("branch")

            # Target branch: check employee doc, fall back to target user doc
            target_branch = doc.get("branch")
            if not target_branch:
                t_user_id = str(doc.get("userId") or "")
                if t_user_id:
                    users_col = get_collection("users")
                    t_user = await users_col.find_one(
                        {"_id": to_object_id(t_user_id)}, {"branch": 1}
                    )
                    target_branch = (t_user or {}).get("branch")
            
            is_self = str(doc["_id"]) == admin_emp_id
            is_same_branch = bool(
                admin_branch and target_branch and str(admin_branch).strip().casefold() == str(target_branch).strip().casefold()
            )
            
            if not is_self and not is_same_branch:
                raise ForbiddenException("You don't have access to this employee")
        except NotFoundException:
            pass
            
    return await _attach_user_info(serialize_doc(doc), include_password=True)


async def get_employee_by_user_id(user_id: str) -> dict:
    employees = get_collection(COLLECTION)
    doc = await employees.find_one({"userId": user_id})
    
    if not doc:
        # Auto-create employee record if it doesn't exist
        # This handles cases where a user was created but no employee record exists
        users = get_collection("users")
        user = await users.find_one({"_id": to_object_id(user_id)})
        if not user:
            raise NotFoundException("User not found")
        
        # Create default employee record
        emp_doc = build_employee_document(user_id=user_id, branch=None)
        result = await employees.insert_one(emp_doc)
        doc = await employees.find_one({"_id": result.inserted_id})
    
    return await _attach_user_info(serialize_doc(doc))


async def update_employee(employee_id: str, payload: EmployeeUpdate, current_user: CurrentUser | None = None) -> dict:
    employees = get_collection(COLLECTION)
    # Check access
    await get_employee(employee_id, current_user)
    
    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        return await get_employee(employee_id)

    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = await employees.find_one_and_update(
        {"_id": to_object_id(employee_id)}, {"$set": update_data}, return_document=True
    )
    if not result:
        raise NotFoundException("Employee not found")

    # If assignedToAdmin changed, cascade to all profiles for this employee
    if "assignedToAdmin" in update_data:
        new_admin_emp_id = str(update_data["assignedToAdmin"] or "")
        # Resolve the admin's display name (employees._id → userId → users.name)
        admin_name = ""
        if new_admin_emp_id:
            admin_emp = await get_collection("employees").find_one(
                {"_id": to_object_id(new_admin_emp_id)}, {"userId": 1}
            )
            if admin_emp and admin_emp.get("userId"):
                admin_user = await get_collection("users").find_one(
                    {"_id": to_object_id(str(admin_emp["userId"]))}, {"name": 1, "email": 1}
                )
                admin_name = (admin_user or {}).get("name") or (admin_user or {}).get("email") or ""
        profiles_col = get_collection("profiles")
        await profiles_col.update_many(
            {"employeeId": employee_id},
            {"$set": {"assignedAdmin": admin_name, "updatedAt": datetime.now(timezone.utc)}},
        )

    return await _attach_user_info(serialize_doc(result))


async def delete_employee(employee_id: str, current_user: CurrentUser | None = None) -> None:
    employees = get_collection(COLLECTION)
    # Check access (ensures employee exists and matches branch)
    emp_doc = await get_employee(employee_id, current_user)

    if current_user and current_user.role == "admin":
        from app.employees.service import get_employee_by_user_id
        admin_emp = await get_employee_by_user_id(current_user.user_id)
        is_self = str(admin_emp.get("id")) == str(employee_id)
        
        # Check target user role
        if not is_self:
            users = get_collection("users")
            target_u = await users.find_one({"_id": to_object_id(str(emp_doc.get("userId")))})
            if target_u and target_u.get("role") in {"admin", "super_admin"}:
                raise ForbiddenException("Admins cannot delete other admins or super admins")
    
    result = await employees.delete_one({"_id": to_object_id(employee_id)})
    if result.deleted_count == 0:
        raise NotFoundException("Employee not found")
