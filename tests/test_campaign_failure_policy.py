import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.campaigns import scheduler, service
from app.core.exceptions import BadRequestException
from app.campaigns.model import CampaignStatus
from bson import ObjectId


def test_worker_active_check_stops_paused_failed_and_deleted_campaigns(monkeypatch):
    class FakeCampaigns:
        document = None

        async def find_one(self, *_args, **_kwargs):
            return self.document

    collection = FakeCampaigns()
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)
    campaign_id = "507f1f77bcf86cd799439011"

    for status in ("running", "processing"):
        collection.document = {"status": status}
        assert asyncio.run(service.is_worker_active(campaign_id)) is True

    for status in ("paused", "failed", "completed"):
        collection.document = {"status": status}
        assert asyncio.run(service.is_worker_active(campaign_id)) is False

    collection.document = None
    assert asyncio.run(service.is_worker_active(campaign_id)) is False


def test_daily_limit_pause_does_not_mark_campaign_failed(monkeypatch):
    campaign = {"status": CampaignStatus.RUNNING.value}

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return {"status": campaign["status"]}

        async def update_one(self, query, update):
            if campaign["status"] != query["status"]:
                return SimpleNamespace(modified_count=0)
            campaign.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    monkeypatch.setattr(service, "get_collection", lambda _name: FakeCampaigns())

    asyncio.run(service.pause_campaign_worker("507f1f77bcf86cd799439011"))

    assert campaign["status"] == CampaignStatus.PAUSED.value
    assert campaign["pausedFromStatus"] == CampaignStatus.RUNNING.value
    assert "errorMessage" not in campaign


def test_scheduler_does_not_complete_a_campaign_paused_by_worker(monkeypatch):
    campaign = {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "status": CampaignStatus.PAUSED.value,
        "recurrenceType": "once",
    }

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return campaign

        async def update_one(self, *_args, **_kwargs):
            return SimpleNamespace(modified_count=0)

    monkeypatch.setattr(scheduler, "get_collection", lambda _name: FakeCampaigns())

    asyncio.run(
        scheduler.finalize_campaign_execution(
            str(campaign["_id"]), success=True
        )
    )

    assert campaign["status"] == CampaignStatus.PAUSED.value


def test_worker_start_does_not_overwrite_a_concurrent_pause(monkeypatch):
    class FakeCampaigns:
        document = {"status": "processing", "startedAt": None}

        async def find_one(self, *_args, **_kwargs):
            self.document["status"] = "paused"
            return {"status": "processing", "startedAt": None}

        async def find_one_and_update(self, query, update, **_kwargs):
            if self.document["status"] != query["status"]:
                return None
            self.document.update(update["$set"])
            return self.document

    collection = FakeCampaigns()
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)

    assert asyncio.run(
        service.start_campaign_worker("507f1f77bcf86cd799439011")
    ) is False
    assert collection.document["status"] == "paused"


@pytest.mark.parametrize(
    "initial_status",
    [CampaignStatus.SCHEDULED.value, CampaignStatus.RESCHEDULED.value],
)
def test_scheduled_run_resets_per_run_sent_count(monkeypatch, initial_status):
    campaign = {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "status": initial_status,
        "executionSent": 50,
    }

    class FakeCampaigns:
        async def find_one_and_update(self, query, update, **_kwargs):
            if campaign["status"] not in query["status"]["$in"]:
                return None
            campaign.update(update["$set"])
            return campaign

    monkeypatch.setattr(scheduler, "get_collection", lambda _name: FakeCampaigns())

    assert asyncio.run(
        scheduler.transition_to_processing("507f1f77bcf86cd799439011")
    )
    assert campaign["status"] == CampaignStatus.PROCESSING.value
    assert campaign["executionSent"] == 0


def test_scheduled_filter_includes_rescheduled_campaigns(monkeypatch):
    class EmptyCursor:
        def sort(self, *_args, **_kwargs):
            return self

        def skip(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    class FakeCampaigns:
        query = None

        async def count_documents(self, query):
            self.query = query
            return 0

        def find(self, query):
            self.query = query
            return EmptyCursor()

    collection = FakeCampaigns()
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)

    asyncio.run(
        service.list_campaigns(
            employee_id="employee-1",
            params=SimpleNamespace(skip=0, page=1, pageSize=20),
            status_filter="scheduled",
        )
    )

    assert collection.query["status"] == {
        "$in": [
            CampaignStatus.SCHEDULED.value,
            CampaignStatus.RESCHEDULED.value,
        ]
    }


def test_rescheduled_campaign_is_selected_when_due(monkeypatch):
    class FakeCursor:
        async def to_list(self, length=None):
            return []

    class FakeCampaigns:
        query = None

        def find(self, query):
            self.query = query
            return FakeCursor()

    collection = FakeCampaigns()
    monkeypatch.setattr(scheduler, "get_collection", lambda _name: collection)

    asyncio.run(scheduler.find_due_campaigns())

    assert collection.query["status"] == {
        "$in": [
            CampaignStatus.SCHEDULED.value,
            CampaignStatus.RESCHEDULED.value,
        ]
    }


def test_successful_recurring_run_uses_rescheduled_status(monkeypatch):
    campaign_id = "507f1f77bcf86cd799439011"
    campaign = {
        "_id": ObjectId(campaign_id),
        "status": CampaignStatus.PROCESSING.value,
        "processingStartedAt": datetime.now(timezone.utc),
        "executionGeneration": 3,
        "recurrenceType": "daily",
        "pending": 10,
        "scheduledForDisplay": "09:00",
        "timezoneOffsetMinutes": 0,
        "employeeId": "employee-1",
        "campaignName": "Recurring campaign",
    }

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return campaign

        async def update_one(self, query, update):
            assert query["executionGeneration"] == 3
            campaign.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    monkeypatch.setattr(scheduler, "get_collection", lambda _name: FakeCampaigns())
    monkeypatch.setattr(scheduler, "create_notification", AsyncMock())

    asyncio.run(
        scheduler.finalize_campaign_execution(
            campaign_id,
            success=True,
            execution_generation=3,
        )
    )

    assert campaign["status"] == CampaignStatus.RESCHEDULED.value
    assert campaign["scheduledFor"] > datetime.now(timezone.utc)


def test_completed_recurring_draft_schedules_automatic_reminder(monkeypatch):
    campaign_id = "507f1f77bcf86cd799439011"
    campaign = {
        "_id": ObjectId(campaign_id),
        "status": CampaignStatus.PROCESSING.value,
        "processingStartedAt": datetime.now(timezone.utc),
        "executionGeneration": 3,
        "recurrenceType": "daily",
        "pending": 0,
        "mailType": "draft",
        "employeeId": "employee-1",
        "campaignName": "Completed recurring draft",
    }

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return campaign

        async def update_one(self, query, update):
            assert query["executionGeneration"] == 3
            campaign.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    schedule_reminder = AsyncMock()
    monkeypatch.setattr(scheduler, "get_collection", lambda _name: FakeCampaigns())
    monkeypatch.setattr(
        "app.campaigns.service.schedule_automatic_reminder_campaign",
        schedule_reminder,
    )
    monkeypatch.setattr(scheduler, "create_notification", AsyncMock())

    asyncio.run(
        scheduler.finalize_campaign_execution(
            campaign_id,
            success=True,
            execution_generation=3,
        )
    )

    assert campaign["status"] == CampaignStatus.COMPLETED.value
    schedule_reminder.assert_awaited_once_with(campaign_id)


def test_reminder_scheduler_failure_is_saved_on_completed_campaign(monkeypatch):
    campaign_id = "507f1f77bcf86cd799439031"
    campaign = {
        "_id": ObjectId(campaign_id),
        "status": CampaignStatus.PROCESSING.value,
        "processingStartedAt": datetime.now(timezone.utc),
        "executionGeneration": 4,
        "recurrenceType": "daily",
        "pending": 0,
        "mailType": "draft",
        "employeeId": "employee-1",
        "campaignName": "Completed recurring draft",
    }

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return campaign

        async def update_one(self, query, update):
            if "status" in query:
                expected_status = query["status"]
                if isinstance(expected_status, dict):
                    assert campaign["status"] in expected_status["$in"]
                else:
                    assert campaign["status"] == expected_status
            campaign.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    monkeypatch.setattr(scheduler, "get_collection", lambda _name: FakeCampaigns())
    monkeypatch.setattr(
        "app.campaigns.service.schedule_automatic_reminder_campaign",
        AsyncMock(side_effect=RuntimeError("test scheduler failure")),
    )
    monkeypatch.setattr(scheduler, "create_notification", AsyncMock())

    asyncio.run(
        scheduler.finalize_campaign_execution(
            campaign_id,
            success=True,
            execution_generation=4,
        )
    )

    assert campaign["status"] == CampaignStatus.COMPLETED.value
    assert campaign["reminderAutomationStatus"] == "failed"
    assert "test scheduler failure" in campaign["reminderAutomationError"]


def test_resumed_scheduled_execution_keeps_run_progress(monkeypatch):
    scheduled_for = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
    campaign = {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "employeeId": "employee-1",
        "status": CampaignStatus.PAUSED.value,
        "pausedFromStatus": CampaignStatus.RUNNING.value,
        "scheduledFor": scheduled_for,
        "processingStartedAt": datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc),
        "executionSent": 50,
    }

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return campaign

        async def find_one_and_update(self, query, update, **_kwargs):
            if campaign["status"] != query["status"]:
                return None
            campaign.update(update["$set"])
            for key in update.get("$unset", {}):
                campaign.pop(key, None)
            return campaign

    monkeypatch.setattr(service, "get_collection", lambda _name: FakeCampaigns())

    resumed, should_start_worker, is_scheduled_execution = asyncio.run(
        service.resume_campaign(
            "507f1f77bcf86cd799439011",
            "employee-1",
            False,
        )
    )

    assert resumed["status"] == CampaignStatus.PROCESSING.value
    assert resumed["scheduledFor"] == scheduled_for.strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    assert resumed["executionSent"] == 50
    assert "pausedFromStatus" not in resumed
    assert should_start_worker is True
    assert is_scheduled_execution is True


def test_scheduled_campaign_cannot_be_paused_before_execution(monkeypatch):
    campaign = {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "employeeId": "employee-1",
        "status": CampaignStatus.SCHEDULED.value,
        "scheduledFor": datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc),
    }

    async def get_owned(*_args, **_kwargs):
        return campaign

    monkeypatch.setattr(service, "_get_campaign_owned", get_owned)
    with pytest.raises(BadRequestException):
        asyncio.run(
            service.set_status(
                "507f1f77bcf86cd799439011",
                CampaignStatus.PAUSED,
                "employee-1",
                False,
            )
        )


def test_running_campaign_resume_starts_worker(monkeypatch):
    campaign = {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "employeeId": "employee-1",
        "status": CampaignStatus.PAUSED.value,
        "pausedFromStatus": CampaignStatus.RUNNING.value,
        "startedAt": datetime.now(timezone.utc),
    }

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return campaign

        async def find_one_and_update(self, query, update, **_kwargs):
            if campaign["status"] != query["status"]:
                return None
            campaign.update(update["$set"])
            for key in update.get("$unset", {}):
                campaign.pop(key, None)
            return campaign

    monkeypatch.setattr(service, "get_collection", lambda _name: FakeCampaigns())

    resumed, should_start_worker, is_scheduled_execution = asyncio.run(
        service.resume_campaign(
            "507f1f77bcf86cd799439011",
            "employee-1",
            False,
        )
    )

    assert resumed["status"] == CampaignStatus.RUNNING.value
    assert should_start_worker is True
    assert is_scheduled_execution is False


def test_scheduled_campaign_failure_is_terminal_and_keeps_error(monkeypatch):
    campaign_id = "507f1f77bcf86cd799439011"
    campaign = {
        "_id": campaign_id,
        "status": CampaignStatus.PROCESSING.value,
        "processingStartedAt": datetime.now(timezone.utc),
        "retryCount": 0,
        "maxRetries": 3,
        "scheduledFor": datetime.now(timezone.utc),
        "campaignName": "Limit test",
        "employeeId": "employee-1",
        "errorMessage": None,
    }

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return campaign

        async def update_one(self, query, update):
            active_statuses = query.get("status", {}).get("$in", [])
            if campaign["status"] not in active_statuses:
                return SimpleNamespace(modified_count=0)
            campaign.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    monkeypatch.setattr(scheduler, "get_collection", lambda _name: FakeCampaigns())
    monkeypatch.setattr(scheduler, "create_notification", AsyncMock())

    asyncio.run(
        scheduler.finalize_campaign_execution(
            campaign_id,
            success=False,
            error_message="SMTP daily sending limit reached",
        )
    )

    assert campaign["status"] == CampaignStatus.FAILED.value
    assert campaign["errorMessage"] == "SMTP daily sending limit reached"
    assert campaign["retryCount"] == 0
