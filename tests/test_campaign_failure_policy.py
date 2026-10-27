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


def test_new_scheduled_run_resets_per_run_sent_count(monkeypatch):
    campaign = {
        "_id": ObjectId("507f1f77bcf86cd799439011"),
        "status": CampaignStatus.SCHEDULED.value,
        "executionSent": 50,
    }

    class FakeCampaigns:
        async def find_one_and_update(self, query, update, **_kwargs):
            if campaign["status"] != query["status"]:
                return None
            campaign.update(update["$set"])
            return campaign

    monkeypatch.setattr(scheduler, "get_collection", lambda _name: FakeCampaigns())

    assert asyncio.run(
        scheduler.transition_to_processing("507f1f77bcf86cd799439011")
    )
    assert campaign["status"] == CampaignStatus.PROCESSING.value
    assert campaign["executionSent"] == 0


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
