from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.campaign_engine.sender import SMTPCredentials, _build_mime_message
from app.campaign_engine import worker
from app.email_master import service as email_master_service
from app.profile_emails import service
from app.campaigns.model import CampaignStatus


class AsyncDocs:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        self.iterator = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeProfileEmailsCollection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query):
        eligible = []
        for doc in self.docs:
            is_draft = doc.get("mailType", "draft") == "draft"
            if (
                doc.get("profileId") == query["profileId"]
                and doc.get("sendStatus") == "sent"
                and is_draft
            ):
                eligible.append(doc)
        return AsyncDocs(eligible)

    async def update_one(self, query, update):
        doc = next(item for item in self.docs if item["_id"] == query["_id"])
        if doc.get("sendStatus") != "sent":
            return SimpleNamespace(modified_count=0)
        doc.update(update["$set"])
        return SimpleNamespace(modified_count=1)


@pytest.mark.anyio
async def test_convert_sent_drafts_only_queues_rows_with_original_thread_data():
    records = [
        {
            "_id": "ready",
            "profileId": "profile1",
            "mailType": "draft",
            "sendStatus": "sent",
            "draftSubject": "Exact original subject",
            "draftMessageId": "<draft@example.test>",
        },
        {
            "_id": "missing-data",
            "profileId": "profile1",
            "mailType": "draft",
            "sendStatus": "sent",
            "draftSubject": None,
            "messageId": None,
        },
    ]
    collection = FakeProfileEmailsCollection(records)

    with (
        patch.object(service, "get_collection", return_value=collection),
        patch.object(service, "get_profile", new_callable=AsyncMock),
    ):
        result = await service.convert_sent_drafts_to_reminders(
            "profile1", "employee1", False
        )

    assert result == {
        "profileId": "profile1",
        "convertedCount": 1,
        "skippedMissingThreadData": 1,
    }
    assert records[0]["mailType"] == "reminder"
    assert records[0]["sendStatus"] == "pending"
    assert records[0]["draftSubject"] == "Exact original subject"
    assert records[1]["mailType"] == "draft"
    assert records[1]["sendStatus"] == "sent"

    with (
        patch.object(service, "get_collection", return_value=collection),
        patch.object(service, "get_profile", new_callable=AsyncMock),
    ):
        retried_result = await service.convert_sent_drafts_to_reminders(
            "profile1", "employee1", False
        )
    assert retried_result["convertedCount"] == 0


@pytest.mark.anyio
async def test_reminder_pending_batch_is_ordered_by_original_draft_sent_date():
    rows = [
        {
            "_id": "later",
            "profileId": "profile1",
            "sendStatus": "pending",
            "mailType": "reminder",
            "sentDate": datetime(2026, 10, 27, tzinfo=timezone.utc),
            "createdAt": datetime(2026, 10, 1, tzinfo=timezone.utc),
        },
        {
            "_id": "earlier",
            "profileId": "profile1",
            "sendStatus": "pending",
            "mailType": "reminder",
            "sentDate": datetime(2026, 10, 26, tzinfo=timezone.utc),
            "createdAt": datetime(2026, 10, 2, tzinfo=timezone.utc),
        },
    ]

    class PendingCursor:
        def __init__(self, documents):
            self.documents = documents

        def sort(self, fields):
            self.documents.sort(
                key=lambda doc: tuple(doc[field] for field, _direction in fields)
            )
            return self

        def limit(self, count):
            self.documents = self.documents[:count]
            return self

        def __aiter__(self):
            return AsyncDocs(self.documents).__aiter__()

    class PendingCollection:
        def find(self, query):
            assert query == {
                "profileId": "profile1",
                "sendStatus": "pending",
                "mailType": "reminder",
            }
            return PendingCursor(rows)

    with patch.object(
        service, "get_collection", return_value=PendingCollection()
    ):
        batch = await service.get_pending_batch(
            "profile1", 10, mail_type="reminder"
        )

    assert [row["id"] for row in batch] == ["earlier", "later"]


@pytest.mark.anyio
async def test_clear_profile_reverses_usage_only_for_pending_draft_rows():
    records = [
        {
            "masterEmailId": "unsent-draft",
            "sendStatus": "pending",
            "mailType": "draft",
        },
        {
            "masterEmailId": "legacy-unsent-draft",
            "sendStatus": "pending",
        },
        {
            "masterEmailId": "sent-draft",
            "sendStatus": "sent",
            "mailType": "draft",
        },
        {
            "masterEmailId": "pending-reminder",
            "sendStatus": "pending",
            "mailType": "reminder",
        },
        {
            "masterEmailId": "failed-draft",
            "sendStatus": "failed",
            "mailType": "draft",
        },
    ]

    class ClearListCollection:
        def find(self, query, projection):
            assert query == {"profileId": "profile1"}
            assert projection == {
                "masterEmailId": 1,
                "sendStatus": 1,
                "mailType": 1,
            }
            return AsyncDocs(records)

        async def delete_many(self, query):
            assert query == {"profileId": "profile1"}
            return SimpleNamespace(deleted_count=len(records))

    collection = ClearListCollection()
    release_locks = AsyncMock()
    decrement_usage = AsyncMock(return_value=2)

    with (
        patch.object(service, "get_collection", return_value=collection),
        patch.object(service, "get_profile", new_callable=AsyncMock),
        patch.object(service, "release_email_locks", release_locks),
        patch.object(service, "decrement_email_usage", decrement_usage),
    ):
        result = await service.clear_profile_list("profile1", "employee1", False)

    assert result == {"deletedCount": 5, "usageCountReversed": 2}
    release_locks.assert_awaited_once_with(
        [
            "unsent-draft",
            "legacy-unsent-draft",
            "sent-draft",
            "pending-reminder",
            "failed-draft",
        ]
    )
    decrement_usage.assert_awaited_once_with(
        ["unsent-draft", "legacy-unsent-draft"]
    )


@pytest.mark.anyio
async def test_decrement_email_usage_only_updates_positive_usage_counts():
    from bson import ObjectId

    master_id = str(ObjectId())
    collection = SimpleNamespace(update_many=AsyncMock(
        return_value=SimpleNamespace(modified_count=1)
    ))
    with patch.object(email_master_service, "get_collection", return_value=collection):
        reversed_count = await email_master_service.decrement_email_usage(
            [master_id, "invalid-id"]
        )

    assert reversed_count == 1
    query = collection.update_many.await_args.args[0]
    update = collection.update_many.await_args.args[1]
    assert query == {
        "_id": {"$in": [ObjectId(master_id)]},
        "usageCount": {"$gt": 0},
    }
    assert update["$inc"] == {"usageCount": -1}


def test_reminder_mime_message_keeps_exact_subject_and_reply_headers():
    credentials = SMTPCredentials(
        email="sender@example.test",
        password="not-used",
        display_name="Sender",
        smtp_host="smtp.example.test",
        smtp_port=587,
        use_tls=True,
    )

    message = _build_mime_message(
        credentials=credentials,
        to="recipient@example.test",
        subject="Exact original subject",
        body_plain="Friendly reminder",
        body_html="Friendly reminder",
        message_id="<reminder@example.test>",
        in_reply_to="<draft@example.test>",
        references="<draft@example.test>",
    )

    assert message["Subject"] == "Exact original subject"
    assert message["In-Reply-To"] == "<draft@example.test>"
    assert message["References"] == "<draft@example.test>"


@pytest.mark.anyio
async def test_reminder_campaign_uses_saved_subject_and_threading_headers(monkeypatch):
    from bson import ObjectId

    campaign_id = str(ObjectId())
    profile_id = str(ObjectId())
    campaign = {
        "_id": ObjectId(campaign_id),
        "profileId": profile_id,
        "employeeId": "employee1",
        "status": CampaignStatus.PROCESSING.value,
        "mailType": "reminder",
        "dailyLimit": 1,
        "recurrenceType": "once",
    }
    profile = {
        "gmailAccount": "sender@example.test",
        "templates": [{"subject": "Different subject", "body": "Reminder body"}],
        "reminderTemplates": [
            {
                "name": "Friendly follow-up",
                "body": "Hello [name], this is a reminder.",
                "weight": 1,
            }
        ],
        "sendingOptions": {"delayMin": 0, "delayMax": 0},
    }
    reminder_row = {
        "id": "profile-email-1",
        "email": "recipient@example.test",
        "mailType": "reminder",
        "draftSubject": "Exact subject from the draft",
        "draftMessageId": "<original@example.test>",
    }
    campaigns_collection = SimpleNamespace(
        find_one=AsyncMock(return_value=campaign)
    )
    profiles_collection = SimpleNamespace(
        find_one=AsyncMock(return_value={"_id": ObjectId(profile_id), **profile})
    )
    monkeypatch.setattr(
        worker,
        "get_collection",
        lambda name: (
            campaigns_collection if name == "campaigns" else profiles_collection
        ),
    )
    monkeypatch.setattr(worker.asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(
        worker,
        "get_credentials_for_send",
        AsyncMock(
            return_value={
                "_id": "account1",
                "email": "sender@example.test",
                "password": "unused",
                "displayName": "Sender",
                "smtpHost": "smtp.example.test",
                "smtpPort": 587,
                "useTls": True,
            }
        ),
    )
    send_email = AsyncMock(
        return_value=SimpleNamespace(
            success=True,
            thread_id="<reminder@example.test>",
            message_id="<reminder@example.test>",
            error="",
        )
    )
    monkeypatch.setattr(worker, "send_email", send_email)
    monkeypatch.setattr(worker, "record_send", AsyncMock())
    monkeypatch.setattr(worker, "record_sent", AsyncMock())
    monkeypatch.setattr(worker, "mark_email_sent", AsyncMock())
    monkeypatch.setattr(worker, "_push_progress", AsyncMock())
    monkeypatch.setattr(worker, "create_notification", AsyncMock())

    campaign_service = SimpleNamespace(
        start_campaign_worker=AsyncMock(return_value=True),
        increment_counters=AsyncMock(),
        finalize_campaign=AsyncMock(),
        is_worker_active=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(worker, "campaign_service", campaign_service)

    get_pending_batch = AsyncMock(side_effect=[[reminder_row], []])
    monkeypatch.setattr(worker.pe_service, "get_pending_batch", get_pending_batch)
    monkeypatch.setattr(
        worker.pe_service, "get_sent_domain_counts_today", AsyncMock(return_value={})
    )
    monkeypatch.setattr(worker.pe_service, "mark_sending", AsyncMock(return_value=True))
    mark_sent = AsyncMock()
    monkeypatch.setattr(worker.pe_service, "mark_sent", mark_sent)

    await worker._run(campaign_id)

    get_pending_batch.assert_any_await(
        profile_id, worker.BATCH_SIZE, mail_type="reminder"
    )
    send_email.assert_awaited_once()
    assert send_email.await_args.kwargs["subject"] == "Exact subject from the draft"
    assert send_email.await_args.kwargs["body_plain"] == (
        "Hello there, this is a reminder."
    )
    assert send_email.await_args.kwargs["in_reply_to"] == "<original@example.test>"
    assert send_email.await_args.kwargs["references"] == "<original@example.test>"
    assert mark_sent.await_args.kwargs["mail_type"] == "reminder"
    assert mark_sent.await_args.kwargs["subject"] == "Exact subject from the draft"
