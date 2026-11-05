from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import BadRequestException
from app.profile_emails import service


@pytest.mark.anyio
async def test_retry_sent_reminders_only_resets_sent_reminder_rows():
    rows = [
        {
            "profileId": "profile1",
            "mailType": "reminder",
            "sendStatus": "sent",
            "draftMessageId": "<original@example.test>",
            "reminderMessageId": "<reminder@example.test>",
        },
        {"profileId": "profile1", "mailType": "reminder", "sendStatus": "failed"},
        {"profileId": "profile1", "mailType": "reminder", "sendStatus": "pending"},
        {"profileId": "profile1", "mailType": "draft", "sendStatus": "sent"},
        {"profileId": "another-profile", "mailType": "reminder", "sendStatus": "sent"},
    ]

    class FakeCampaigns:
        async def find_one(self, query, projection):
            assert query == {
                "profileId": "profile1",
                "mailType": "reminder",
                "status": {
                    "$in": [
                        "pending",
                        "running",
                        "paused",
                        "scheduled",
                        "rescheduled",
                        "processing",
                    ]
                },
            }
            assert projection == {"_id": 1}
            return None

    class FakeProfileEmails:
        async def update_many(self, query, update):
            assert query == {
                "profileId": "profile1",
                "mailType": "reminder",
                "sendStatus": "sent",
            }
            assert update["$set"]["sendStatus"] == "pending"
            assert update["$set"]["errorMessage"] is None
            assert isinstance(update["$set"]["updatedAt"], datetime)
            matched = [
                row
                for row in rows
                if row["profileId"] == query["profileId"]
                and row["mailType"] == query["mailType"]
                and row["sendStatus"] == query["sendStatus"]
            ]
            for row in matched:
                row.update(update["$set"])
            return SimpleNamespace(modified_count=len(matched))

    with (
        patch.object(service, "get_profile", new_callable=AsyncMock),
        patch.object(
            service,
            "get_collection",
            side_effect=lambda name: (
                FakeCampaigns() if name == "campaigns" else FakeProfileEmails()
            ),
        ),
    ):
        result = await service.retry_sent_reminders("profile1", "employee1", False)

    assert result == {"profileId": "profile1", "resetCount": 1}
    assert rows[0]["sendStatus"] == "pending"
    assert rows[0]["draftMessageId"] == "<original@example.test>"
    assert rows[0]["reminderMessageId"] == "<reminder@example.test>"
    assert rows[1]["sendStatus"] == "failed"
    assert rows[2]["sendStatus"] == "pending"
    assert rows[3]["sendStatus"] == "sent"
    assert rows[4]["sendStatus"] == "sent"


@pytest.mark.anyio
async def test_retry_sent_reminders_rejects_profile_with_active_reminder_campaign():
    class FakeCampaigns:
        async def find_one(self, _query, _projection):
            return {"_id": "active-campaign"}

    profile_emails = SimpleNamespace(update_many=AsyncMock())

    with (
        patch.object(service, "get_profile", new_callable=AsyncMock),
        patch.object(
            service,
            "get_collection",
            side_effect=lambda name: (
                FakeCampaigns() if name == "campaigns" else profile_emails
            ),
        ),
    ):
        with pytest.raises(BadRequestException, match="active reminder campaign"):
            await service.retry_sent_reminders("profile1", "employee1", False)

    profile_emails.update_many.assert_not_awaited()
