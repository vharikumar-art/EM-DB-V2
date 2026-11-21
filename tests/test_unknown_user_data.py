import re
from unittest.mock import AsyncMock

from bson import ObjectId
import pytest

from app.core.dependencies import CurrentUser
from app.core import dependencies
from app.core.exceptions import NotFoundException
from app.profiles import service as profiles_service
from app.users import unknown
from app.users import service as user_service


class AsyncCursor:
    def __init__(self, documents):
        self.documents = documents

    def __aiter__(self):
        async def iterate():
            for document in self.documents:
                yield document

        return iterate()

    def sort(self, *_args):
        return self

    async def to_list(self, _length=None):
        return self.documents


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = documents or []
        self.updates = []

    def find(self, query=None, *_args):
        query = query or {}
        values = query.get("employeeId", {}).get("$in")
        if values is None:
            return AsyncCursor([
                document
                for document in self.documents
                if all(
                    (
                        isinstance(value, dict)
                        and "$regex" in value
                        and re.search(
                            value["$regex"],
                            str(document.get(key) or ""),
                            re.IGNORECASE
                            if value.get("$options") == "i"
                            else 0,
                        )
                    )
                    or document.get(key) == value
                    for key, value in query.items()
                )
            ])
        return AsyncCursor([
            document
            for document in self.documents
            if document.get("employeeId") in values
        ])

    async def find_one(self, query, *_args):
        for document in self.documents:
            matches = True
            for key, value in query.items():
                if key == "_id" and isinstance(value, dict) and "$ne" in value:
                    matches = document.get("_id") != value["$ne"]
                elif document.get(key) != value:
                    matches = False
                if not matches:
                    break
            if matches:
                return document
        return None

    async def update_one(self, query, update, **kwargs):
        self.updates.append((query, update))
        for document in self.documents:
            if document.get("_id") == query.get("_id"):
                document.update(update.get("$set", {}))
                break
        else:
            if kwargs.get("upsert"):
                document = {"_id": query.get("_id")}
                document.update(update.get("$set", {}))
                self.documents.append(document)

    async def update_many(self, query, update, **kwargs):
        self.updates.append((query, update, kwargs))
        for document in self.documents:
            if "employeeId" in query:
                values = query["employeeId"].get("$in", [])
                if document.get("employeeId") not in values:
                    continue
            if "uploadedBy" in query and document.get("uploadedBy") != query["uploadedBy"]:
                continue
            document.update(update.get("$set", {}))

    async def insert_one(self, document):
        self.documents.append(document)


@pytest.mark.anyio
async def test_full_admin_default_context_includes_scoped_unknown_owners(monkeypatch):
    admin_id = str(ObjectId())
    admin_employee_id = str(ObjectId())
    deleted_employee_id = str(ObjectId())
    employees = FakeCollection([])
    users = FakeCollection([])
    monkeypatch.setattr(
        "app.database.mongodb.get_collection",
        lambda name: {"employees": employees, "users": users}[name],
    )
    monkeypatch.setattr(
        unknown,
        "get_collection",
        lambda name: {"employees": employees, "users": users}[name],
    )
    monkeypatch.setattr(
        "app.employees.service.get_employee_by_user_id",
        AsyncMock(return_value={
            "id": admin_employee_id,
            "branch": "Chennai",
        }),
    )
    monkeypatch.setattr(
        "app.users.unknown.resolve_unknown_employee_ids",
        AsyncMock(return_value=[unknown.UNKNOWN_EMPLOYEE_ID, deleted_employee_id]),
    )

    employee_ids, is_admin = await dependencies.resolve_employee_context(
        CurrentUser(admin_id, "admin", "full")
    )

    assert is_admin is True
    assert deleted_employee_id in employee_ids
    assert unknown.UNKNOWN_EMPLOYEE_ID not in employee_ids


@pytest.mark.anyio
async def test_shared_unknown_identity_is_an_inactive_user_and_employee(monkeypatch):
    users = FakeCollection()
    employees = FakeCollection()
    monkeypatch.setattr(
        unknown,
        "get_collection",
        lambda name: {"users": users, "employees": employees}[name],
    )

    user_id, employee_id = await unknown.ensure_unknown_identity()

    assert user_id == unknown.UNKNOWN_USER_ID
    assert employee_id == unknown.UNKNOWN_EMPLOYEE_ID
    assert users.documents[0]["name"] == "Unknown"
    assert users.documents[0]["status"] == "inactive"
    assert users.documents[0]["systemAccount"] == unknown.UNKNOWN_MARKER
    assert employees.documents[0]["userId"] == user_id


@pytest.mark.anyio
async def test_legacy_employee_id_is_recovered_only_when_unambiguous(monkeypatch):
    former_user_id = str(ObjectId())
    legacy_employee_id = str(ObjectId())
    profiles = FakeCollection([{
        "employeeName": "Former User",
        "employeeId": legacy_employee_id,
    }])
    employees = FakeCollection([])
    monkeypatch.setattr(
        unknown,
        "get_collection",
        lambda name: {"profiles": profiles, "employees": employees}[name],
    )

    assert await unknown.find_legacy_employee_id_for_user(
        former_user_id,
        "Former User",
    ) == legacy_employee_id

    profiles.documents.append({
        "employeeName": "Former User",
        "employeeId": str(ObjectId()),
    })
    assert await unknown.find_legacy_employee_id_for_user(
        former_user_id,
        "Former User",
    ) is None


@pytest.mark.anyio
async def test_unknown_is_not_returned_from_user_management_endpoints(monkeypatch):
    unknown_user = {
        "_id": ObjectId(unknown.UNKNOWN_USER_ID),
        "name": "Unknown",
        "email": "unknown@system.invalid",
        "systemAccount": unknown.UNKNOWN_MARKER,
    }
    users = FakeCollection([unknown_user])
    monkeypatch.setattr(user_service, "get_collection", lambda _name: users)

    listed = await user_service.list_users(
        CurrentUser(str(ObjectId()), "super_admin")
    )
    assert listed == []

    with pytest.raises(NotFoundException, match="User not found"):
        await user_service.get_user_by_id(unknown.UNKNOWN_USER_ID)


@pytest.mark.anyio
async def test_deleted_user_data_is_mapped_to_unknown_and_profile_lists_resolve_it(
    monkeypatch,
):
    user_id = str(ObjectId())
    employee_id = str(ObjectId())
    profile_id = ObjectId()
    existing_unknown_profile_id = ObjectId()
    profiles = FakeCollection([
        {
            "_id": profile_id,
            "employeeId": employee_id,
            "profileName": "Shared name",
        },
        {
            "_id": existing_unknown_profile_id,
            "employeeId": unknown.UNKNOWN_EMPLOYEE_ID,
            "profileName": "Shared name",
        },
        {
            "_id": ObjectId(),
            "employeeId": employee_id,
            "profileName": "Unique profile",
        },
    ])
    accounts = FakeCollection([
        {"_id": ObjectId(), "employeeId": employee_id, "email": "same@example.test"},
        {
            "_id": ObjectId(),
            "employeeId": unknown.UNKNOWN_EMPLOYEE_ID,
            "email": "same@example.test",
        },
        {"_id": ObjectId(), "employeeId": employee_id, "email": "other@example.test"},
    ])
    collections = {
        "profiles": profiles,
        "email_accounts": accounts,
        "deleted_user_mappings": FakeCollection(),
        "filter_dropdowns": FakeCollection(),
    }
    for name in (
        "campaigns",
        "profile_emails",
        "emails",
        "logs",
        "notifications",
        "daily_send_stats",
        "templates",
        "email_master",
    ):
        collections[name] = FakeCollection()
    collections["email_master"] = FakeCollection([
        {
            "_id": ObjectId(),
            "uploadedBy": user_id,
            "uploadedByName": "Former User",
        }
    ])
    monkeypatch.setattr(unknown, "get_collection", lambda name: collections[name])
    monkeypatch.setattr(
        unknown, "ensure_unknown_identity", AsyncMock(
            return_value=(unknown.UNKNOWN_USER_ID, unknown.UNKNOWN_EMPLOYEE_ID)
        )
    )
    monkeypatch.setattr(
        "app.email_master.service.invalidate_dropdown_cache", AsyncMock()
    )

    await unknown.preserve_deleted_user_data(
        user_id,
        employee_id,
        "Former User",
        branch="Vellore",
        assigned_to_admin="admin-1",
    )

    assert profiles.documents[0]["employeeId"] == employee_id
    assert profiles.documents[0]["employeeName"] == "Unknown"
    assert profiles.documents[2]["employeeId"] == employee_id
    assert accounts.documents[0]["employeeId"] == employee_id
    assert accounts.documents[2]["employeeId"] == employee_id

    mappings = collections["deleted_user_mappings"]
    monkeypatch.setattr(profiles_service, "get_collection", lambda _name: profiles)
    monkeypatch.setattr(unknown, "get_collection", lambda _name: mappings)
    result = await profiles_service.list_profiles(unknown.UNKNOWN_EMPLOYEE_ID)

    assert {profile["id"] for profile in result} == {
        str(profile_id),
        str(existing_unknown_profile_id),
        str(profiles.documents[2]["_id"]),
    }
    assert mappings.documents[0]["branch"] == "Vellore"
    scoped_ids = await unknown.resolve_unknown_employee_ids(
        branch="Vellore",
        include_all=False,
    )
    assert employee_id in scoped_ids
    assert user_id in scoped_ids
    assert mappings.documents[0]["employeeId"] == employee_id
    assert mappings.documents[0]["deletedName"] == "Former User"
    assert mappings.documents[0]["branch"] == "Vellore"
    assert mappings.documents[0]["assignedToAdmin"] == "admin-1"
    assert collections["email_master"].documents[0]["uploadedBy"] == unknown.UNKNOWN_USER_ID
    assert collections["email_master"].documents[0]["uploadedByName"] == "Unknown"
