from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from app.core.dependencies import CurrentUser
from app.options import router


class AsyncCursor:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        async def iterate():
            for doc in self.docs:
                yield doc

        return iterate()


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None, *args, **kwargs):
        query = query or {}
        return AsyncCursor([
            doc for doc in self.docs
            if all(doc.get(key) == value for key, value in query.items())
        ])

    async def find_one(self, query, *args, **kwargs):
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None


@pytest.mark.anyio
async def test_super_admin_employee_options_include_super_admin_users(monkeypatch):
    super_admin_id = ObjectId()
    admin_employee_id = ObjectId()
    employee_id = ObjectId()
    users = FakeCollection([
        {
            "_id": super_admin_id,
            "role": "super_admin",
            "name": "Primary Admin",
            "email": "primary@example.test",
            "branch": "HQ",
        },
        {
            "_id": ObjectId(),
            "role": "admin",
            "name": "Admin User",
            "email": "admin@example.test",
        },
    ])
    employees = FakeCollection([
        {"_id": admin_employee_id, "userId": "admin-user"},
        {"_id": employee_id, "userId": "employee-user"},
    ])
    monkeypatch.setattr(
        router,
        "get_collection",
        lambda name: {"users": users, "employees": employees}[name],
    )
    monkeypatch.setattr(
        "app.employees.service.list_employees",
        AsyncMock(return_value=[
            {
                "id": str(admin_employee_id),
                "userId": "admin-user",
                "name": "Admin User",
                "email": "admin@example.test",
            },
            {
                "id": str(employee_id),
                "userId": "employee-user",
                "name": "Employee User",
                "email": "employee@example.test",
            },
        ]),
    )

    result = await router.get_employees_options(
        CurrentUser(str(super_admin_id), "super_admin")
    )

    assert any(
        item["userId"] == str(super_admin_id)
        and item["name"] == "Primary Admin"
        and item["id"] == str(super_admin_id)
        and item["role"] == "super_admin"
        for item in result.data
    )


@pytest.mark.anyio
async def test_admin_employee_options_do_not_include_super_admin_users(monkeypatch):
    admin_id = ObjectId()
    users = FakeCollection([
        {
            "_id": ObjectId(),
            "role": "super_admin",
            "name": "Primary Admin",
            "email": "primary@example.test",
        },
    ])
    employees = FakeCollection([])
    monkeypatch.setattr(
        router,
        "get_collection",
        lambda name: {"users": users, "employees": employees}[name],
    )
    monkeypatch.setattr(
        "app.employees.service.list_employees",
        AsyncMock(return_value=[
            {
                "id": "admin-employee-id",
                "userId": str(admin_id),
                "name": "Branch Admin",
                "email": "admin@example.test",
            }
        ]),
    )

    result = await router.get_employees_options(
        CurrentUser(str(admin_id), "admin")
    )

    assert [item["userId"] for item in result.data] == [str(admin_id)]
