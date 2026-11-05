from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from app.campaigns import service
from app.core.exceptions import BadRequestException
from app.profile_emails import service as profile_email_service


class AsyncDocs:
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


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("reminder_delay_days", "expected_scheduled_for"),
    [
        (None, datetime(2026, 11, 7, 9, 30, tzinfo=timezone.utc)),
        (2, datetime(2026, 11, 3, 9, 30, tzinfo=timezone.utc)),
    ],
)
async def test_completed_draft_campaign_schedules_reminder_after_configured_delay(
    reminder_delay_days,
    expected_scheduled_for,
):
    source_id = ObjectId()
    reminder_id = ObjectId()
    completed_at = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
    source_campaign = {
        "_id": source_id,
        "campaignName": "Initial campaign",
        "profileId": "profile1",
        "employeeId": "employee1",
        "mailType": "draft",
        "status": "completed",
        "completedAt": completed_at,
    }
    if reminder_delay_days is not None:
        source_campaign["reminderDelayDays"] = reminder_delay_days
    inserted_documents = []
    assignment_queries = []
    claim_queries = []

    class FakeCampaigns:
        async def update_one(self, query, update):
            claim_queries.append(query)
            if query["_id"] == source_id:
                source_campaign.update(update["$set"])
                return SimpleNamespace(modified_count=1)
            return SimpleNamespace(modified_count=1)

        async def find_one(self, query):
            return source_campaign

        async def insert_one(self, document):
            inserted_documents.append(document)
            return SimpleNamespace(inserted_id=reminder_id)

    class FakeProfileEmails:
        async def update_many(self, query, update):
            assignment_queries.append(query)
            return SimpleNamespace(modified_count=2)

    def fake_get_collection(name):
        return FakeCampaigns() if name == "campaigns" else FakeProfileEmails()

    with (
        patch.object(service, "get_collection", side_effect=fake_get_collection),
        patch.object(
            service,
            "get_profile",
            new_callable=AsyncMock,
            return_value={
                "isActive": True,
                "profileName": "Demo",
                "gmailAccount": "sender@example.com",
                "reminderTemplates": [{"body": "Checking in"}],
                "sendingOptions": {"dailyLimit": 25},
            },
        ),
        patch(
            "app.profile_emails.service.convert_campaign_sent_drafts_to_reminders",
            new_callable=AsyncMock,
            return_value={"convertedCount": 2, "skippedMissingThreadData": 0},
        ) as convert_to_reminders,
        patch.object(service, "create_notification", new_callable=AsyncMock),
    ):
        await service.schedule_automatic_reminder_campaign(str(source_id))

    reminder_campaign = inserted_documents[0]
    assert reminder_campaign["mailType"] == "reminder"
    assert reminder_campaign["status"] == "scheduled"
    assert reminder_campaign["totalEmails"] == 2
    assert reminder_campaign["scheduledFor"] == expected_scheduled_for
    assert claim_queries[0]["reminderAutomationStatus"] == {
        "$in": [None, "skipped", "failed"]
    }
    assert claim_queries[0]["autoReminderEnabled"] == {"$ne": False}
    assert reminder_campaign["sourceCampaignId"] == str(source_id)
    assert source_campaign["reminderAutomationStatus"] == "scheduled"
    assert source_campaign["reminderCampaignId"] == str(reminder_id)
    assert assignment_queries[0] == {
        "profileId": "profile1",
        "campaignId": str(source_id),
        "mailType": "reminder",
        "sendStatus": "pending",
    }
    convert_to_reminders.assert_awaited_once_with(
        profile_id="profile1",
        employee_id="employee1",
        is_admin=True,
        campaign_id=str(source_id),
    )


@pytest.mark.anyio
async def test_campaign_completion_triggers_reminder_scheduling():
    campaign_id = str(ObjectId())

    class FakeCampaigns:
        async def find_one(self, query):
            return {
                "_id": ObjectId(campaign_id),
                "employeeId": "employee1",
                "profileId": "profile1",
                "campaignName": "Initial campaign",
                "sent": 1,
                "failed": 0,
            }

        async def update_one(self, query, update):
            return SimpleNamespace(modified_count=1)

    class FakeLogs:
        async def insert_one(self, document):
            return None

    def fake_get_collection(name):
        return FakeCampaigns() if name == "campaigns" else FakeLogs()

    with (
        patch.object(service, "get_collection", side_effect=fake_get_collection),
        patch.object(service, "create_notification", new_callable=AsyncMock),
        patch.object(
            service,
            "schedule_automatic_reminder_campaign",
            new_callable=AsyncMock,
        ) as schedule_reminder,
    ):
        await service.finalize_campaign(campaign_id)

    schedule_reminder.assert_awaited_once_with(campaign_id)


@pytest.mark.anyio
async def test_automatic_conversion_is_limited_to_the_completed_campaign():
    campaign_id = str(ObjectId())
    record = {
        "_id": "email-row",
        "profileId": "profile1",
        "campaignId": campaign_id,
        "mailType": "draft",
        "sendStatus": "sent",
        "draftSubject": "Original subject",
        "draftMessageId": "<original@example.test>",
    }

    class FakeProfileEmails:
        def find(self, query):
            assert query["campaignId"] == campaign_id
            return AsyncDocs([record])

        async def find_one(self, *_args, **_kwargs):
            return None

        async def update_one(self, query, update):
            assert query["campaignId"] == campaign_id
            record.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    with (
        patch.object(
            profile_email_service,
            "get_collection",
            side_effect=lambda name: FakeProfileEmails()
            if name == "profile_emails"
            else SimpleNamespace(find_one=AsyncMock(return_value=None)),
        ),
        patch.object(profile_email_service, "get_profile", new_callable=AsyncMock),
    ):
        result = await profile_email_service.convert_campaign_sent_drafts_to_reminders(
            "profile1",
            "employee1",
            True,
            campaign_id=campaign_id,
        )

    assert result["convertedCount"] == 1
    assert record["mailType"] == "reminder"
    assert record["sendStatus"] == "pending"


@pytest.mark.anyio
async def test_automatic_conversion_recovers_subject_from_single_campaign_template():
    campaign_id = str(ObjectId())
    record = {
        "_id": ObjectId(),
        "profileId": "profile1",
        "campaignId": campaign_id,
        "mailType": "draft",
        "sendStatus": "sent",
        "draftSubject": None,
        "draftMessageId": None,
        "messageId": "<original@example.test>",
        "templateId": "default",
        "fullName": "Ada Lovelace",
    }

    class FakeProfileEmails:
        def find(self, query):
            assert query["campaignId"] == campaign_id
            return AsyncDocs([record])

        async def update_one(self, query, update):
            assert query["campaignId"] == campaign_id
            record.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    class FakeCampaigns:
        async def find_one(self, query, projection=None):
            assert query["_id"] == ObjectId(campaign_id)
            return {
                "profileSnapshot": {
                    "templates": [
                        {
                            "name": "Default",
                            "subject": "Hello [first_name]",
                            "body": "Original message",
                        }
                    ]
                }
            }

    def fake_get_collection(name):
        return FakeCampaigns() if name == "campaigns" else FakeProfileEmails()

    with (
        patch.object(
            profile_email_service,
            "get_collection",
            side_effect=fake_get_collection,
        ),
        patch.object(profile_email_service, "get_profile", new_callable=AsyncMock),
    ):
        result = await profile_email_service.convert_campaign_sent_drafts_to_reminders(
            "profile1",
            "employee1",
            True,
            campaign_id=campaign_id,
        )

    assert result["convertedCount"] == 1
    assert record["mailType"] == "reminder"
    assert record["sendStatus"] == "pending"
    assert record["draftSubject"] == "Hello Ada"
    assert record["draftMessageId"] == "<original@example.test>"


@pytest.mark.anyio
async def test_automatic_conversion_recovers_selected_index_from_legacy_templates():
    campaign_id = str(ObjectId())
    record = {
        "_id": ObjectId(),
        "profileId": "profile1",
        "campaignId": campaign_id,
        "mailType": "draft",
        "sendStatus": "sent",
        "templateId": "index:1",
        "draftSubject": None,
        "messageId": "<original@example.test>",
        "fullName": "Ada Lovelace",
    }

    class FakeProfileEmails:
        def find(self, _query):
            return AsyncDocs([record])

        async def update_one(self, _query, update):
            record.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    class FakeCampaigns:
        async def find_one(self, _query, _projection=None):
            return {
                "profileSnapshot": {
                    "templates": [
                        {"subject": "First subject"},
                        {"subject": "Second [first_name] subject"},
                    ]
                }
            }

    with (
        patch.object(
            profile_email_service,
            "get_collection",
            side_effect=lambda name: (
                FakeCampaigns() if name == "campaigns" else FakeProfileEmails()
            ),
        ),
        patch.object(profile_email_service, "get_profile", new_callable=AsyncMock),
    ):
        result = await profile_email_service.convert_campaign_sent_drafts_to_reminders(
            "profile1",
            "employee1",
            True,
            campaign_id=campaign_id,
        )

    assert result["convertedCount"] == 1
    assert record["draftSubject"] == "Second Ada subject"
    assert record["draftMessageId"] == "<original@example.test>"


@pytest.mark.anyio
async def test_manual_conversion_loads_each_row_campaign_snapshot_and_thread_id():
    campaign_id = str(ObjectId())
    record = {
        "_id": ObjectId(),
        "profileId": "profile1",
        "campaignId": campaign_id,
        "mailType": "draft",
        "sendStatus": "sent",
        "templateId": "index:1",
        "draftSubject": None,
        "draftMessageId": None,
        "messageId": None,
        "threadId": "<original@example.test>",
        "fullName": "Ada Lovelace",
    }

    class FakeProfileEmails:
        def find(self, query):
            assert "campaignId" not in query
            return AsyncDocs([record])

        async def update_one(self, _query, update):
            record.update(update["$set"])
            return SimpleNamespace(modified_count=1)

    class FakeCampaigns:
        async def find_one(self, query, _projection=None):
            assert query["_id"] == ObjectId(campaign_id)
            return {
                "profileSnapshot": {
                    "templates": [
                        {"subject": "First subject"},
                        {"subject": "Second [first_name] subject"},
                    ]
                }
            }

    with (
        patch.object(
            profile_email_service,
            "get_collection",
            side_effect=lambda name: (
                FakeCampaigns() if name == "campaigns" else FakeProfileEmails()
            ),
        ),
        patch.object(profile_email_service, "get_profile", new_callable=AsyncMock),
    ):
        result = await profile_email_service.convert_sent_drafts_to_reminders(
            "profile1",
            "employee1",
            True,
        )

    assert result["convertedCount"] == 1
    assert record["mailType"] == "reminder"
    assert record["sendStatus"] == "pending"
    assert record["draftSubject"] == "Second Ada subject"
    assert record["draftMessageId"] == "<original@example.test>"


@pytest.mark.anyio
async def test_manual_reminder_retry_runs_for_completed_campaign():
    campaign_id = str(ObjectId())
    source = {
        "_id": ObjectId(campaign_id),
        "campaignName": "Initial campaign",
        "mailType": "draft",
        "status": "completed",
        "reminderAutomationStatus": "skipped",
    }

    class FakeCampaigns:
        async def find_one(self, query):
            assert query["_id"] == ObjectId(campaign_id)
            return {**source, "reminderAutomationStatus": "scheduled"}

    with (
        patch.object(service, "_get_campaign_owned", new_callable=AsyncMock, return_value=source),
        patch.object(
            service,
            "schedule_automatic_reminder_campaign",
            new_callable=AsyncMock,
        ) as schedule_reminder,
        patch.object(service, "get_collection", return_value=FakeCampaigns()),
    ):
        result = await service.retry_automatic_reminder_campaign(
            campaign_id,
            "employee1",
            False,
        )

    schedule_reminder.assert_awaited_once_with(campaign_id)
    assert result["reminderAutomationStatus"] == "scheduled"


@pytest.mark.anyio
async def test_manual_reminder_retry_does_not_duplicate_scheduled_campaign():
    campaign_id = str(ObjectId())
    source = {
        "_id": ObjectId(campaign_id),
        "mailType": "draft",
        "status": "completed",
        "reminderAutomationStatus": "scheduled",
        "reminderCampaignId": str(ObjectId()),
    }

    with (
        patch.object(service, "_get_campaign_owned", new_callable=AsyncMock, return_value=source),
        patch.object(
            service,
            "schedule_automatic_reminder_campaign",
            new_callable=AsyncMock,
        ) as schedule_reminder,
    ):
        result = await service.retry_automatic_reminder_campaign(
            campaign_id,
            "employee1",
            False,
        )

    schedule_reminder.assert_not_awaited()
    assert result["reminderAutomationStatus"] == "scheduled"


@pytest.mark.anyio
async def test_manual_reminder_retry_rejects_campaign_that_is_not_completed():
    campaign_id = str(ObjectId())
    source = {
        "_id": ObjectId(campaign_id),
        "mailType": "draft",
        "status": "running",
    }

    with (
        patch.object(service, "_get_campaign_owned", new_callable=AsyncMock, return_value=source),
        patch.object(
            service,
            "schedule_automatic_reminder_campaign",
            new_callable=AsyncMock,
        ) as schedule_reminder,
    ):
        with pytest.raises(BadRequestException, match="only be retried for completed"):
            await service.retry_automatic_reminder_campaign(
                campaign_id,
                "employee1",
                False,
            )

    schedule_reminder.assert_not_awaited()


@pytest.mark.anyio
async def test_completed_campaign_with_legacy_rows_schedules_recovered_reminders():
    source_id = ObjectId()
    reminder_id = ObjectId()
    completed_at = datetime(2026, 11, 1, 9, 30, tzinfo=timezone.utc)
    source_campaign = {
        "_id": source_id,
        "campaignName": "Initial campaign",
        "profileId": "profile1",
        "employeeId": "employee1",
        "mailType": "draft",
        "status": "completed",
        "completedAt": completed_at,
        "profileSnapshot": {
            "templates": [{"name": "Default", "subject": "Original [first_name]"}],
        },
    }
    records = [
        {
            "_id": ObjectId(),
            "profileId": "profile1",
            "campaignId": str(source_id),
            "mailType": "draft",
            "sendStatus": "sent",
            "draftSubject": None,
            "draftMessageId": None,
            "messageId": f"<original-{index}@example.test>",
            "templateId": "default",
            "fullName": f"Lead {index}",
        }
        for index in range(6)
    ]
    inserted_documents = []

    class FakeCampaigns:
        async def update_one(self, query, update):
            if query["_id"] == source_id:
                source_campaign.update(update["$set"])
            return SimpleNamespace(modified_count=1)

        async def find_one(self, query, projection=None):
            if query["_id"] == source_id:
                return source_campaign
            return next(
                (doc for doc in inserted_documents if doc.get("_id") == query["_id"]),
                None,
            )

        async def insert_one(self, document):
            inserted = {**document, "_id": reminder_id}
            inserted_documents.append(inserted)
            return SimpleNamespace(inserted_id=reminder_id)

    class FakeProfileEmails:
        def find(self, query):
            return AsyncDocs(
                [
                    record
                    for record in records
                    if record["campaignId"] == query["campaignId"]
                    and record["sendStatus"] == "sent"
                    and record["mailType"] == "draft"
                ]
            )

        async def update_one(self, query, update):
            record = next(record for record in records if record["_id"] == query["_id"])
            record.update(update["$set"])
            return SimpleNamespace(modified_count=1)

        async def update_many(self, query, update):
            matched = [
                record
                for record in records
                if record["profileId"] == query["profileId"]
                and record["campaignId"] == query["campaignId"]
                and record["mailType"] == query["mailType"]
                and record["sendStatus"] == query["sendStatus"]
            ]
            for record in matched:
                record.update(update["$set"])
            return SimpleNamespace(modified_count=len(matched))

    campaigns_collection = FakeCampaigns()
    emails_collection = FakeProfileEmails()

    with (
        patch.object(
            service,
            "get_collection",
            side_effect=lambda name: (
                campaigns_collection if name == "campaigns" else emails_collection
            ),
        ),
        patch.object(
            profile_email_service,
            "get_collection",
            side_effect=lambda name: (
                campaigns_collection if name == "campaigns" else emails_collection
            ),
        ),
        patch.object(
            service,
            "get_profile",
            new_callable=AsyncMock,
            return_value={
                "isActive": True,
                "profileName": "Demo",
                "gmailAccount": "sender@example.com",
                "reminderTemplates": [{"body": "Checking in"}],
                "sendingOptions": {"dailyLimit": 25},
            },
        ),
        patch.object(
            profile_email_service,
            "get_profile",
            new_callable=AsyncMock,
        ),
        patch.object(service, "create_notification", new_callable=AsyncMock),
    ):
        await service.schedule_automatic_reminder_campaign(str(source_id))

    assert len(inserted_documents) == 1
    reminder_campaign = inserted_documents[0]
    assert reminder_campaign["mailType"] == "reminder"
    assert reminder_campaign["status"] == "scheduled"
    assert reminder_campaign["totalEmails"] == 6
    assert reminder_campaign["scheduledFor"] == datetime(
        2026, 11, 7, 9, 30, tzinfo=timezone.utc
    )
    assert source_campaign["reminderAutomationStatus"] == "scheduled"
    assert source_campaign["reminderCampaignId"] == str(reminder_id)
    assert all(record["mailType"] == "reminder" for record in records)
    assert all(record["campaignId"] == str(reminder_id) for record in records)
    assert all(record["draftSubject"] == "Original Lead" for record in records)
    assert all(record["draftMessageId"] == record["messageId"] for record in records)
