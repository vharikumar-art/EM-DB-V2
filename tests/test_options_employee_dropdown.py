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
    monkeypatch.setattr(
        router,
        "_unknown_employee_ids_for_dropdown",
        AsyncMock(return_value=["000000000000000000000002"]),
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
    monkeypatch.setattr(
        router,
        "_unknown_employee_ids_for_dropdown",
        AsyncMock(return_value=["000000000000000000000002"]),
    )

    result = await router.get_employees_options(
        CurrentUser(str(admin_id), "admin")
    )

    assert [item["userId"] for item in result.data] == [str(admin_id)]


@pytest.mark.anyio
async def test_unknown_is_available_after_a_scoped_user_deletion(monkeypatch):
    unknown_user_id = "000000000000000000000001"
    unknown_employee_id = "000000000000000000000002"
    monkeypatch.setattr(
        router,
        "get_collection",
        lambda _name: FakeCollection([]),
    )
    monkeypatch.setattr(
        "app.employees.service.list_employees",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        router,
        "_unknown_employee_ids_for_dropdown",
        AsyncMock(return_value=[unknown_employee_id, str(ObjectId())]),
    )

    result = await router.get_employees_options(
        CurrentUser(str(ObjectId()), "super_admin")
    )

    assert result.data == [{
        "id": unknown_employee_id,
        "userId": unknown_user_id,
        "name": "Unknown",
        "email": "unknown@system.invalid",
        "branch": "",
    }]


@pytest.mark.anyio
async def test_unknown_profile_options_use_scoped_deleted_employee_ids(monkeypatch):
    admin = CurrentUser(str(ObjectId()), "admin")
    deleted_employee_id = str(ObjectId())
    resolve_context = AsyncMock(return_value=([deleted_employee_id], True))
    list_profiles = AsyncMock(return_value=[{
        "id": "profile-id",
        "profileName": "Deleted owner's profile",
        "gmailAccount": "sender@example.test",
    }])
    monkeypatch.setattr(router, "resolve_employee_context", resolve_context)
    monkeypatch.setattr(router, "list_profiles", list_profiles)

    result = await router.get_profiles_options(
        "000000000000000000000002",
        admin,
    )

    resolve_context.assert_awaited_once_with(
        admin,
        "000000000000000000000002",
    )
    list_profiles.assert_awaited_once_with([deleted_employee_id])
    assert result.data[0]["profileName"] == "Deleted owner's profile"


@pytest.mark.anyio
async def test_vellore_full_admin_gets_unknown_employee_option_only_from_vellore(
    monkeypatch,
):
    admin = CurrentUser(str(ObjectId()), "admin", "full")
    admin_employee_id = str(ObjectId())
    deleted_employee_id = str(ObjectId())
    get_employee = AsyncMock(return_value={
        "id": admin_employee_id,
        "branch": "VELLORE",
    })
    resolve_unknown = AsyncMock(return_value=[
        "000000000000000000000002",
        deleted_employee_id,
    ])
    monkeypatch.setattr(router, "get_collection", lambda _name: FakeCollection([]))
    monkeypatch.setattr(
        "app.employees.service.list_employees",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(router, "get_employee_by_user_id", get_employee)
    monkeypatch.setattr(router, "resolve_unknown_employee_ids", resolve_unknown)

    result = await router.get_employees_options(admin)

    resolve_unknown.assert_awaited_once_with(
        branch="VELLORE",
        include_all=False,
    )
    assert result.data == [{
        "id": "000000000000000000000002",
        "userId": "000000000000000000000001",
        "name": "Unknown",
        "email": "unknown@system.invalid",
        "branch": "",
    }]
