import asyncio
from datetime import datetime, timezone

from app.core.dependencies import CurrentUser
from app.dashboard import service
from app.dashboard.schema import DashboardQuery, DateRangePreset


class FakeCursor:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        async def iterate():
            for doc in self.docs:
                yield doc

        return iterate()

    async def to_list(self, length=None):
        return self.docs


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, *args, **kwargs):
        return FakeCursor(self.docs)

    def aggregate(self, pipeline):
        return FakeCursor([])


class FakeLogsCollection(FakeCollection):
    def aggregate(self, pipeline):
        if "$sort" in pipeline[1]:
            return FakeCursor(self.docs)
        return FakeCursor([])


def test_upload_history_merges_user_id_and_employee_id_logs(monkeypatch):
    user_id = "user-1"
    employee_id = "employee-1"
    now = datetime.now(timezone.utc)
    logs = FakeLogsCollection([
        {
            "employeeId": user_id,
            "action": "UPLOAD",
            "runDate": now,
            "uploadedCount": 10,
            "uniqueCount": 7,
            "duplicateCount": 2,
        },
        {
            "employeeId": employee_id,
            "action": "UPLOAD",
            "runDate": now,
            "uploadedCount": 5,
            "uniqueCount": 3,
            "duplicateCount": 1,
        },
    ])
    collections = {
        "logs": logs,
        "users": FakeCollection([{
            "_id": user_id,
            "name": "Test Employee",
            "email": "employee@example.com",
        }]),
        "employees": FakeCollection([{"_id": employee_id, "userId": user_id}]),
        "profile_emails": FakeCollection(),
        "campaigns": FakeCollection(),
    }
    monkeypatch.setattr(service, "get_collection", lambda name: collections[name])

    result = asyncio.run(
        service.get_upload_history(
            DashboardQuery(preset=DateRangePreset.TODAY),
            employee_id=employee_id,
            current_user=CurrentUser("admin-user", "super_admin"),
        )
    )

    assert len(result["records"]) == 1
    assert result["records"][0]["employeeId"] == user_id
    assert result["records"][0]["uploadCount"] == 15
    assert result["records"][0]["uniqueCount"] == 10
    assert result["records"][0]["duplicateCount"] == 3
    assert result["records"][0]["invalidCount"] == 2
    assert result["totals"] == {
        "totalUploads": 15,
        "totalUnique": 10,
        "totalDuplicate": 3,
        "totalInvalid": 2,
    }