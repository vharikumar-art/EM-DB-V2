import re

import pytest
from bson import ObjectId

from app.core.dependencies import CurrentUser
from app.employees import service


class AsyncCursor:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        async def iterate():
            for doc in self.docs:
                yield doc

        return iterate()


class EmployeeCollection:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    def find(self, query=None, *args, **kwargs):
        query = query or {}
        self.queries.append(query)
        if "assignedToAdmin" in query:
            docs = [
                doc for doc in self.docs
                if doc.get("assignedToAdmin") == query["assignedToAdmin"]
            ]
        elif "$or" in query:
            clauses = query["$or"]
            employee_id = clauses[0]["_id"]
            user_ids = clauses[1]["userId"]["$in"]
            docs = [
                doc for doc in self.docs
                if doc["_id"] == employee_id
                or doc.get("userId") in user_ids
            ]
        else:
            docs = self.docs
        return AsyncCursor(docs)


class UserCollection:
    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    def find(self, query=None, *args, **kwargs):
        query = query or {}
        self.queries.append(query)
        docs = []
        for user in self.docs:
            if "role" in query and user.get("role") != query["role"]:
                continue
            branch_filter = query.get("branch")
            if branch_filter:
                branch = user.get("branch") or ""
                if not re.search(branch_filter["$regex"], branch, re.IGNORECASE):
                    continue
            docs.append(user)
        return AsyncCursor(docs)

    async def find_one(self, query, *args, **kwargs):
        for user in self.docs:
            if all(user.get(key) == value for key, value in query.items()):
                return user
        return None


@pytest.mark.anyio
async def test_partial_admin_employee_list_is_limited_to_assigned_employees(monkeypatch):
    admin_employee_id = ObjectId()
    admin_user_id = ObjectId()
    assigned_employee_id = ObjectId()
    assigned_user_id = ObjectId()
    other_employee_id = ObjectId()
    other_user_id = ObjectId()
    employees = EmployeeCollection([
        {
            "_id": admin_employee_id,
            "userId": str(admin_user_id),
            "branch": "North",
        },
        {
            "_id": assigned_employee_id,
            "userId": str(assigned_user_id),
            "assignedToAdmin": str(admin_employee_id),
        },
        {
            "_id": other_employee_id,
            "userId": str(other_user_id),
            "assignedToAdmin": "another-admin",
        },
    ])
    users = UserCollection([
        {"_id": admin_user_id, "name": "Admin", "email": "admin@example.test", "status": "active"},
        {"_id": assigned_user_id, "name": "Assigned", "email": "assigned@example.test", "status": "active"},
        {"_id": other_user_id, "name": "Other", "email": "other@example.test", "status": "active"},
    ])
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: {"employees": employees, "users": users}[name],
    )
    monkeypatch.setattr(
        service,
        "get_employee_by_user_id",
        lambda _user_id: _async_value({
            "id": str(admin_employee_id),
            "branch": "North",
        }),
    )

    result = await service.list_employees(
        CurrentUser(str(admin_user_id), "admin", "partial")
    )

    assert employees.queries == [{"assignedToAdmin": str(admin_employee_id)}]
    assert [employee["id"] for employee in result] == [str(assigned_employee_id)]


@pytest.mark.anyio
async def test_full_admin_employee_list_is_limited_to_admin_branch(monkeypatch):
    admin_employee_id = ObjectId()
    admin_user_id = ObjectId()
    branch_employee_id = ObjectId()
    branch_user_id = ObjectId()
    employees = EmployeeCollection([
        {
            "_id": admin_employee_id,
            "userId": str(admin_user_id),
            "branch": "North",
        },
        {
            "_id": branch_employee_id,
            "userId": str(branch_user_id),
        },
    ])
    users = UserCollection([
        {"_id": admin_user_id, "name": "Admin", "email": "admin@example.test", "status": "active"},
        {
            "_id": branch_user_id,
            "role": "employee",
            "branch": "North",
            "name": "North Employee",
            "email": "north@example.test",
            "status": "active",
        },
    ])
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: {"employees": employees, "users": users}[name],
    )
    monkeypatch.setattr(
        service,
        "get_employee_by_user_id",
        lambda _user_id: _async_value({
            "id": str(admin_employee_id),
            "branch": "North",
        }),
    )

    result = await service.list_employees(
        CurrentUser(str(admin_user_id), "admin", "full")
    )

    assert len(result) == 2
    assert any(employee["id"] == str(branch_employee_id) for employee in result)
    assert any(employee["id"] == str(admin_employee_id) for employee in result)


async def _async_value(value):
    return value
