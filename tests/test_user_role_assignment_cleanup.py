import asyncio

from bson import ObjectId
import pytest

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException
from app.users.model import UserRole
from app.users.schema import UserUpdate
from app.users import service


class FakeUsersCollection:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, query, projection=None):
        return self.doc if query.get("_id") == self.doc["_id"] else None

    async def find_one_and_update(self, query, update, return_document=True):
        self.doc.update(update["$set"])
        return self.doc


class FakeEmployeesCollection:
    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, query, projection=None):
        return next(
            (doc for doc in self.docs if doc.get("userId") == query.get("userId")),
            None,
        )

    async def update_many(self, query, update):
        assigned_ids = query["assignedToAdmin"]["$in"]
        for doc in self.docs:
            if doc.get("assignedToAdmin") in assigned_ids:
                doc.update(update["$set"])

    async def update_one(self, query, update):
        for doc in self.docs:
            if doc.get("_id") == query.get("_id"):
                doc.update(update["$set"])
                return


def test_demoting_admin_unassigns_subordinate_employees(monkeypatch):
    admin_user_id = ObjectId()
    admin_employee_id = ObjectId()
    user_doc = {"_id": admin_user_id, "role": UserRole.ADMIN.value}
    employees = FakeEmployeesCollection([
        {"_id": admin_employee_id, "userId": str(admin_user_id)},
        {"_id": ObjectId(), "assignedToAdmin": str(admin_employee_id)},
    ])
    users = FakeUsersCollection(user_doc)
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: users if name == "users" else employees,
    )
    monkeypatch.setattr(service, "serialize_user_with_password", lambda doc: doc)

    asyncio.run(
        service.update_user(
            str(admin_user_id),
            UserUpdate(role=UserRole.EMPLOYEE),
            CurrentUser("super-admin", "super_admin", "full"),
        )
    )

    assert user_doc["role"] == UserRole.EMPLOYEE.value
    assert employees.docs[1]["assignedToAdmin"] is None


def test_promoting_employee_to_admin_clears_its_admin_assignment(monkeypatch):
    user_id = ObjectId()
    employee_id = ObjectId()
    user_doc = {"_id": user_id, "role": UserRole.EMPLOYEE.value}
    employee_doc = {
        "_id": employee_id,
        "userId": str(user_id),
        "assignedToAdmin": str(ObjectId()),
    }
    users = FakeUsersCollection(user_doc)
    employees = FakeEmployeesCollection([employee_doc])
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: users if name == "users" else employees,
    )
    monkeypatch.setattr(service, "serialize_user_with_password", lambda doc: doc)

    asyncio.run(
        service.update_user(
            str(user_id),
            UserUpdate(role=UserRole.ADMIN, assignedToAdmin=str(ObjectId())),
            CurrentUser("super-admin", "super_admin", "full"),
        )
    )

    assert user_doc["role"] == UserRole.ADMIN.value
    assert user_doc["accessLevel"] == "full"
    assert employee_doc["assignedToAdmin"] is None


def test_admin_cannot_change_user_role(monkeypatch):
    user_id = ObjectId()
    users = FakeUsersCollection({"_id": user_id, "role": UserRole.EMPLOYEE.value})
    monkeypatch.setattr(service, "get_collection", lambda name: users)

    with pytest.raises(ForbiddenException, match="Only super admins"):
        asyncio.run(
            service.update_user(
                str(user_id),
                UserUpdate(role=UserRole.ADMIN),
                CurrentUser("admin", "admin", "full"),
            )
        )