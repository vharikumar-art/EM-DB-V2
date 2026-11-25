import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from bson import ObjectId

from app.campaigns import scheduler, service
from app.campaigns.model import CampaignStatus


CAMPAIGN_ID = "507f1f77bcf86cd799439011"


def test_scheduled_resume_advances_execution_generation(monkeypatch):
    campaign = {
        "_id": ObjectId(CAMPAIGN_ID),
        "employeeId": "employee-1",
        "status": CampaignStatus.PAUSED.value,
        "processingStartedAt": datetime.now(timezone.utc),
        "scheduledFor": datetime.now(timezone.utc),
        "executionGeneration": 1,
    }

    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return campaign

        async def find_one_and_update(self, _query, update, **_kwargs):
            campaign.update(update["$set"])
            for key, amount in update["$inc"].items():
                campaign[key] = campaign.get(key, 0) + amount
            for key in update["$unset"]:
                campaign.pop(key, None)
            return campaign

    monkeypatch.setattr(service, "_get_campaign_owned", AsyncMock(return_value=campaign))
    monkeypatch.setattr(service, "get_collection", lambda _name: FakeCampaigns())

    resumed, should_start_worker, is_scheduled_execution = asyncio.run(
        service.resume_campaign(CAMPAIGN_ID, "employee-1", False)
    )

    assert resumed["status"] == CampaignStatus.PROCESSING.value
    assert resumed["executionGeneration"] == 2
    assert should_start_worker is True
    assert is_scheduled_execution is True


def test_scheduler_does_not_finalize_an_older_execution(monkeypatch):
    class FakeCampaigns:
        updates = 0

        async def find_one(self, *_args, **_kwargs):
            return {
                "_id": ObjectId(CAMPAIGN_ID),
                "status": CampaignStatus.PROCESSING.value,
                "executionGeneration": 2,
            }

        async def update_one(self, *_args, **_kwargs):
            self.updates += 1

    campaigns = FakeCampaigns()
    monkeypatch.setattr(scheduler, "get_collection", lambda _name: campaigns)

    asyncio.run(
        scheduler.finalize_campaign_execution(
            CAMPAIGN_ID,
            True,
            execution_generation=1,
        )
    )

    assert campaigns.updates == 0


def test_resumed_scheduler_execution_retries_after_worker_lock_contention(monkeypatch):
    class FakeCampaigns:
        async def find_one(self, *_args, **_kwargs):
            return {
                "status": CampaignStatus.PROCESSING.value,
                "executionGeneration": 2,
            }

    execute = AsyncMock(side_effect=[(None, None), (True, None)])
    finalize = AsyncMock()
    monkeypatch.setattr(scheduler, "get_collection", lambda _name: FakeCampaigns())
    monkeypatch.setattr(scheduler, "execute_campaign", execute)
    monkeypatch.setattr(scheduler, "finalize_campaign_execution", finalize)
    monkeypatch.setattr(scheduler.asyncio, "sleep", AsyncMock())

    asyncio.run(
        scheduler._execute_and_finalize(
            CAMPAIGN_ID,
            "Campaign",
            execution_generation=2,
        )
    )

    assert execute.await_count == 2
    finalize.assert_awaited_once_with(CAMPAIGN_ID, True, None, 2)

