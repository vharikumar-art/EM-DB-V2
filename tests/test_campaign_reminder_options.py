from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from bson import ObjectId

from app.campaigns import scheduler, service
from app.campaigns.model import CampaignStatus
from app.campaigns.schema import CampaignScheduleRequest, CampaignStartRequest


@pytest.mark.parametrize(
    "request_type, request_data",
    [
        (CampaignStartRequest, {"profileId": "profile1"}),
        (
            CampaignScheduleRequest,
            {
                "profileId": "profile1",
                "scheduledTimeLocal": "09:00",
                "timezoneOffsetMinutes": -330,
            },
        ),
    ],
)
@pytest.mark.parametrize("empty_value", [None, ""])
def test_reminder_delay_defaults_to_six_for_empty_values(
    request_type,
    request_data,
    empty_value,
):
    request = request_type(**request_data, reminderDelayDays=empty_value)

    assert request.autoReminderEnabled is True
    assert request.reminderDelayDays == 6


@pytest.mark.parametrize("delay_days", [1, 6, 15])
def test_reminder_delay_accepts_values_from_one_through_fifteen(delay_days):
    request = CampaignStartRequest(
        profileId="profile1",
        autoReminderEnabled=False,
        reminderDelayDays=delay_days,
    )

    assert request.autoReminderEnabled is False
    assert request.reminderDelayDays == delay_days


@pytest.mark.parametrize("delay_days", [0, 16, -1])
def test_reminder_delay_rejects_values_outside_one_through_fifteen(delay_days):
    with pytest.raises(ValidationError):
        CampaignStartRequest(profileId="profile1", reminderDelayDays=delay_days)


@pytest.mark.anyio
@pytest.mark.parametrize("scheduled", [False, True])
async def test_campaign_creation_persists_reminder_options(scheduled):
    campaign_id = ObjectId()
    inserted_campaign = None

    class FakeCampaigns:
        async def find_one(self, query):
            if query.get("_id") == campaign_id:
                return inserted_campaign
            return None

        async def insert_one(self, document):
            nonlocal inserted_campaign
            inserted_campaign = {**document, "_id": campaign_id}
            return SimpleNamespace(inserted_id=campaign_id)

    class FakeProfileEmails:
        async def count_documents(self, _query):
            return 1

        async def update_many(self, _query, _update):
            return SimpleNamespace(modified_count=1)

    campaigns = FakeCampaigns()
    profile_emails = FakeProfileEmails()

    if scheduled:
        payload = CampaignScheduleRequest(
            profileId="profile1",
            scheduledTimeLocal="09:00",
            timezoneOffsetMinutes=0,
            recurrenceType="daily",
            autoReminderEnabled=False,
            reminderDelayDays="",
        )
        create = service.create_scheduled_campaign
    else:
        payload = CampaignStartRequest(
            profileId="profile1",
            autoReminderEnabled=False,
            reminderDelayDays=None,
        )
        create = service.create_campaign

    with (
        patch.object(
            service,
            "get_collection",
            side_effect=lambda name: campaigns if name == "campaigns" else profile_emails,
        ),
        patch.object(
            service,
            "get_profile",
            new_callable=AsyncMock,
            return_value={
                "isActive": True,
                "employeeId": "employee1",
                "profileName": "Demo",
                "sendingOptions": {"dailyLimit": 10},
            },
        ),
        patch.object(service, "create_notification", new_callable=AsyncMock),
    ):
        response = await create(payload, "employee1", False)

    assert inserted_campaign["autoReminderEnabled"] is False
    assert inserted_campaign["reminderDelayDays"] == 6
    assert inserted_campaign["reminderAutomationStatus"] == "disabled"
    assert response["autoReminderEnabled"] is False
    assert response["reminderDelayDays"] == 6


@pytest.mark.anyio
async def test_immediate_campaign_completion_skips_disabled_automatic_reminder():
    campaign_id = ObjectId()
    campaign = {
        "_id": campaign_id,
        "status": CampaignStatus.RUNNING.value,
        "mailType": "draft",
        "autoReminderEnabled": False,
        "employeeId": "employee1",
        "profileId": "profile1",
        "campaignName": "Draft",
        "sent": 1,
        "failed": 0,
    }

    class FakeCampaigns:
        async def find_one(self, _query):
            return campaign

        async def update_one(self, _query, _update):
            return SimpleNamespace(modified_count=1)

    class FakeLogs:
        async def insert_one(self, _document):
            return None

    with (
        patch.object(
            service,
            "get_collection",
            side_effect=lambda name: FakeCampaigns() if name == "campaigns" else FakeLogs(),
        ),
        patch.object(service, "create_notification", new_callable=AsyncMock),
        patch.object(
            service,
            "schedule_automatic_reminder_campaign",
            new_callable=AsyncMock,
        ) as schedule_reminder,
    ):
        await service.finalize_campaign(str(campaign_id))

    schedule_reminder.assert_not_awaited()


@pytest.mark.anyio
async def test_scheduled_campaign_completion_skips_disabled_automatic_reminder():
    campaign_id = ObjectId()
    campaign = {
        "_id": campaign_id,
        "status": CampaignStatus.PROCESSING.value,
        "mailType": "draft",
        "autoReminderEnabled": False,
        "employeeId": "employee1",
        "campaignName": "Scheduled draft",
    }

    class FakeCampaigns:
        async def find_one(self, _query):
            return campaign

        async def update_one(self, _query, _update):
            return SimpleNamespace(modified_count=1)

    with (
        patch.object(scheduler, "get_collection", return_value=FakeCampaigns()),
        patch.object(scheduler, "create_notification", new_callable=AsyncMock),
        patch(
            "app.campaigns.service.schedule_automatic_reminder_campaign",
            new_callable=AsyncMock,
        ) as schedule_reminder,
    ):
        await scheduler.finalize_campaign_execution(str(campaign_id), success=True)

    schedule_reminder.assert_not_awaited()
