import asyncio
from bson import ObjectId

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
        "waiting_for_mails",
        "failed",
        "paused",
    ]


def test_effective_generation_limit_caps_requested_batch_size():
    from app.profile_emails import service as profile_emails_service

    assert profile_emails_service._get_effective_generation_limit(1000, 0, False) == 600
    assert profile_emails_service._get_effective_generation_limit(1000, 400, False) == 400
    assert profile_emails_service._get_effective_generation_limit(1000, 1000, False) == 600
    assert profile_emails_service._get_effective_generation_limit(1000, 0, True) == 1000
