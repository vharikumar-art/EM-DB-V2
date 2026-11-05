import asyncio
from types import SimpleNamespace
from bson import ObjectId

from app.core.dependencies import CurrentUser
from app.users import service


class FakeEmployeesCollection:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, query, projection=None):
        if query.get("userId") == "user-123":
            return self.doc
        return None


def test_resolve_employee_id_for_user(monkeypatch):
    employee_id = ObjectId()

    def fake_get_collection(name):
        assert name == "employees"
        return FakeEmployeesCollection({"_id": employee_id, "userId": "user-123"})

    monkeypatch.setattr(service, "get_collection", fake_get_collection)

    result = asyncio.run(service._resolve_employee_id_for_user("user-123"))

    assert result == str(employee_id)


def test_running_campaign_statuses_exclude_scheduled():
    assert service._get_running_campaign_statuses() == ["running", "processing"]


def test_pending_campaign_statuses_include_failed_and_paused():
    assert service._get_pending_campaign_statuses() == [
        "pending",
        "scheduled",
        "rescheduled",
        "waiting_for_mails",
        "failed",
        "paused",
    ]


def test_effective_generation_limit_uses_user_requested_value_without_fixed_cap():
    from app.profile_emails import service as profile_emails_service

    # blank/zero daily values default to 100
    assert profile_emails_service._get_effective_generation_limit(0, 0, False) == 100
    assert profile_emails_service._get_effective_generation_limit(None, 0, False) == 100
    assert profile_emails_service._get_effective_generation_limit("", 0, False) == 100

    # custom values are respected and no fixed cap is enforced
    assert profile_emails_service._get_effective_generation_limit(1000, 0, False) == 1000
    assert profile_emails_service._get_effective_generation_limit(1000, 400, False) == 400
    assert profile_emails_service._get_effective_generation_limit(1000, 1000, False) == 1000
    assert profile_emails_service._get_effective_generation_limit(3000, 0, False) == 3000
    assert profile_emails_service._get_effective_generation_limit(1000, 5000, False) == 5000
    assert profile_emails_service._get_effective_generation_limit(1000, 0, True) == 1000


def test_partial_admin_lists_themselves_and_assigned_employees(monkeypatch):
    admin_user_id = ObjectId()
    admin_employee_id = ObjectId()
    assigned_user_id = ObjectId()
    assigned_employee_id = ObjectId()
    other_user_id = ObjectId()
    admin_doc = {
        "_id": admin_user_id,
        "name": "Partial Admin",
        "email": "admin@example.test",
        "role": "admin",
    }
    assigned_doc = {
        "_id": assigned_user_id,
        "name": "Assigned Employee",
        "email": "employee@example.test",
        "role": "employee",
    }
    other_doc = {
        "_id": other_user_id,
        "name": "Other Employee",
        "email": "other@example.test",
        "role": "employee",
    }

    class AsyncCursor:
        def __init__(self, documents):
            self.documents = documents

        def __aiter__(self):
            self.iterator = iter(self.documents)
            return self

        async def __anext__(self):
            try:
                return next(self.iterator)
            except StopIteration:
                raise StopAsyncIteration

        async def to_list(self, _length=None):
            return self.documents

    class UsersCollection:
        async def find_one(self, *_args, **_kwargs):
            return None

        def find(self, query):
            visible_ids = set(query["_id"]["$in"])
            return AsyncCursor(
                [
                    user
                    for user in (admin_doc, assigned_doc, other_doc)
                    if user["_id"] in visible_ids
                ]
            )

        def aggregate(self, _pipeline):
            return AsyncCursor([])

    class EmployeesCollection:
        def find(self, query, _projection=None):
            if query.get("assignedToAdmin") == str(admin_employee_id):
                return AsyncCursor(
                    [
                        {
                            "_id": assigned_employee_id,
                            "userId": str(assigned_user_id),
                            "assignedToAdmin": str(admin_employee_id),
                        }
                    ]
                )
            user_ids = set(query.get("userId", {}).get("$in", []))
            return AsyncCursor(
                [
                    {
                        "_id": assigned_employee_id,
                        "userId": str(assigned_user_id),
                        "assignedToAdmin": str(admin_employee_id),
                    }
                    for user_id in user_ids
                    if user_id == str(assigned_user_id)
                ]
            )

    users_collection = UsersCollection()
    employees_collection = EmployeesCollection()

    def fake_get_collection(name):
        if name == "users":
            return users_collection
        if name == "employees":
            return employees_collection
        return SimpleNamespace(aggregate=lambda _pipeline: AsyncCursor([]))

    async def fake_get_employee_by_user_id(_user_id):
        return {"id": str(admin_employee_id)}

    monkeypatch.setattr(service, "get_collection", fake_get_collection)
    monkeypatch.setattr(
        "app.employees.service.get_employee_by_user_id",
        fake_get_employee_by_user_id,
    )

    result = asyncio.run(
        service.list_users(
            CurrentUser(str(admin_user_id), "admin", access_level="partial")
        )
    )

    assert {user["id"] for user in result} == {
        str(admin_user_id),
        str(assigned_user_id),
    }
