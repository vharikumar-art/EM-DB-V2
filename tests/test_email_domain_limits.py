import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId
from app.campaign_engine import worker
from app.email_master import service as email_master_service
from app.email_master.service import _apply_profile_email_domain_limits
from app.profile_emails import service as profile_email_service


class EmailDomainLimitTests(unittest.TestCase):
    def test_duplicate_upload_refreshes_upload_metadata_without_insert(self):
        existing_id = ObjectId()

        class Cursor:
            def __init__(self, documents):
                self.documents = iter(documents)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.documents)
                except StopIteration:
                    raise StopAsyncIteration

        class MasterCollection:
            def __init__(self):
                self.update_call = None
                self.insert_called = False

            def find(self, _query, _projection):
                return Cursor([{"email": "known@example.com", "_id": existing_id}])

            async def update_many(self, query, update):
                self.update_call = (query, update)

            async def insert_many(self, _documents):
                self.insert_called = True

        class LogsCollection:
            async def insert_one(self, _document):
                return None

        master_collection = MasterCollection()

        async def fake_notification(**_kwargs):
            return None

        with (
            patch.object(
                email_master_service,
                "get_collection",
                side_effect=lambda name: (
                    master_collection if name == "email_master"
                    else LogsCollection()
                ),
            ),
            patch.object(
                email_master_service,
                "parse_file_bytes",
                return_value=object(),
            ),
            patch.object(
                email_master_service,
                "validate_and_clean_rows",
                return_value=(
                    [{"email": "known@example.com"}],
                    [],
                ),
            ),
            patch.object(
                email_master_service,
                "create_notification",
                fake_notification,
            ),
        ):
            asyncio.run(
                email_master_service.upload_file(
                    uploaded_by_id="uploader-1",
                    uploaded_by_name="Uploader",
                    file_bytes=b"email\nknown@example.com",
                    filename="emails.csv",
                )
            )

        self.assertEqual(
            master_collection.update_call[0],
            {"_id": {"$in": [existing_id]}},
        )
        self.assertEqual(
            set(master_collection.update_call[1]["$set"]),
            {"uploadedDate", "uploadedBy", "uploadedByName"},
        )
        self.assertEqual(
            master_collection.update_call[1]["$set"]["uploadedBy"],
            "uploader-1",
        )
        self.assertEqual(
            master_collection.update_call[1]["$set"]["uploadedByName"],
            "Uploader",
        )
        self.assertIsNotNone(
            master_collection.update_call[1]["$set"]["uploadedDate"].tzinfo
        )
        self.assertFalse(master_collection.insert_called)

    def test_gmail_is_kept_and_non_gmail_domains_are_capped_after_filters(self):
        records = [
            {
                "_id": ObjectId(),
                "email": f"gmail{index}@gmail.com",
                "country": "INDIA",
                "isDuplicate": False,
                "hasReply": False,
                "inProfileEmails": False,
                "usageCount": 0,
            }
            for index in range(150)
        ] + [
            {
                "_id": ObjectId(),
                "email": f"school{index}@gtm.edu.in",
                "country": "INDIA",
                "isDuplicate": False,
                "hasReply": False,
                "inProfileEmails": False,
                "usageCount": 0,
            }
            for index in range(25)
        ] + [
            {
                "_id": ObjectId(),
                "email": f"school{index}@acme.edu.in",
                "country": "INDIA",
                "isDuplicate": False,
                "hasReply": False,
                "inProfileEmails": False,
                "usageCount": 0,
            }
            for index in range(25)
        ]

        class Cursor:
            def __init__(self, documents):
                self.documents = documents

            def limit(self, _amount):
                return self

            def __aiter__(self):
                self.documents = iter(self.documents)
                return self

            async def __anext__(self):
                try:
                    return next(self.documents)
                except StopIteration:
                    raise StopAsyncIteration

        class Collection:
            def __init__(self, documents):
                self.documents = documents
                self.pipeline = None

            async def count_documents(self, query):
                self.query = query
                return len(self.documents)

            def aggregate(self, pipeline):
                self.pipeline = pipeline
                return Cursor(self.documents)

        collection = Collection(records)
        with patch.object(
            email_master_service, "get_collection", return_value=collection
        ):
            selected = asyncio.run(
                email_master_service.query_for_profile(
                    filters={"country": ["INDIA"]},
                    daily_limit=200,
                    filter_limit=200,
                )
            )

        self.assertEqual(collection.pipeline[0]["$match"]["country"]["$in"][0].pattern, "^INDIA$")
        self.assertNotIn("email", collection.pipeline[0]["$match"])
        self.assertEqual(len(selected), 170)
        self.assertEqual(
            sum(record["email"].endswith("@gmail.com") for record in selected),
            150,
        )
        self.assertEqual(
            sum(record["email"].endswith("@gtm.edu.in") for record in selected),
            10,
        )
        self.assertEqual(
            sum(record["email"].endswith("@acme.edu.in") for record in selected),
            10,
        )

    def test_profile_filters_with_only_gmail_candidates_keep_all_matches(self):
        records = [
            {
                "_id": ObjectId(),
                "email": f"user{index}@gmail.com",
                "country": "INDIA",
                "isDuplicate": False,
                "hasReply": False,
                "inProfileEmails": False,
                "usageCount": 0,
            }
            for index in range(10)
        ]

        class Cursor:
            def __init__(self, documents):
                self.documents = iter(documents)

            def limit(self, _amount):
                return self

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.documents)
                except StopIteration:
                    raise StopAsyncIteration

        class Collection:
            async def count_documents(self, _query):
                return len(records)

            def aggregate(self, _pipeline):
                return Cursor(records)

        with patch.object(
            email_master_service, "get_collection", return_value=Collection()
        ):
            selected = asyncio.run(
                email_master_service.query_for_profile(
                    filters={"country": ["INDIA"]},
                    daily_limit=100,
                    filter_limit=100,
                )
            )

        self.assertEqual(len(selected), 10)
        self.assertTrue(all(record["email"].endswith("@gmail.com") for record in selected))

    def test_domain_cap_scales_with_requested_generation_limit(self):
        records = [
            {"id": str(index), "email": f"user{index}@example.com"}
            for index in range(250)
        ]

        for requested_limit, expected in (
            (100, 5),
            (101, 10),
            (200, 10),
            (201, 15),
            (600, 30),
        ):
            with self.subTest(requested_limit=requested_limit):
                selected = _apply_profile_email_domain_limits(
                    records, requested_limit
                )
                self.assertEqual(len(selected), expected)

    def test_limit_600_keeps_550_matches_when_domains_are_diverse(self):
        records = [
            {
                "id": str(index),
                "email": f"user{index}@domain{index % 20}.example",
            }
            for index in range(550)
        ]

        selected = _apply_profile_email_domain_limits(records, 600)

        self.assertEqual(len(selected), 550)

    def test_gmail_is_exempt_from_selection_cap_and_other_domains_are_case_insensitive(self):
        records = [
            {"id": f"gmail-{index}", "email": f"user{index}@GMAIL.com"}
            for index in range(10)
        ] + [
            {"id": str(index), "email": f"user{index}@Example.COM"}
            for index in range(20)
        ]

        selected = _apply_profile_email_domain_limits(records, 100)

        self.assertEqual(len(selected), 15)
        self.assertEqual(
            sum(record["email"].casefold().endswith("@gmail.com") for record in selected),
            10,
        )
        self.assertEqual(
            sum(record["email"].casefold().endswith("@example.com") for record in selected),
            5,
        )

    def test_today_sent_domain_counts_are_case_insensitive(self):
        class Cursor:
            def __aiter__(self):
                self.records = iter([
                    {"email": "one@Example.com"},
                    {"email": "two@example.COM"},
                    {"email": "three@other.org"},
                ])
                return self

            async def __anext__(self):
                try:
                    return next(self.records)
                except StopIteration:
                    raise StopAsyncIteration

        class Collection:
            def find(self, query, projection):
                self.query = query
                self.projection = projection
                return Cursor()

        collection = Collection()
        with patch.object(
            profile_email_service, "get_collection", return_value=collection
        ):
            counts = asyncio.run(
                profile_email_service.get_sent_domain_counts_today("profile-1")
            )

        self.assertEqual(counts, {"example.com": 2, "other.org": 1})
        self.assertEqual(collection.query["profileId"], "profile-1")
        self.assertEqual(collection.query["sendStatus"], "sent")

    def test_campaign_sends_at_most_five_same_domain_emails_per_day(self):
        campaign_id = ObjectId()
        profile_id = ObjectId()
        employee_id = "employee-1"
        campaign = {
            "_id": campaign_id,
            "profileId": str(profile_id),
            "employeeId": employee_id,
            "dailyLimit": 100,
            "recurrenceType": "once",
            "status": "running",
            "campaignName": "Domain cap test",
        }
        profile = {
            "_id": profile_id,
            "employeeId": employee_id,
            "profileName": "Test profile",
            "gmailAccount": "sender@example.com",
            "sendingOptions": {"delayMin": 0, "delayMax": 0},
            "templates": [{"subject": "Hello", "body": "Hello"}],
        }
        records = [
            {
                "id": str(ObjectId()),
                "email": f"recipient{index}@school.example",
                "sendStatus": "pending",
            }
            for index in range(6)
        ] + [
            {
                "id": str(ObjectId()),
                "email": f"gmail{index}@gmail.com",
                "sendStatus": "pending",
            }
            for index in range(6)
        ]
        sent_emails: list[str] = []
        abort_calls: list[tuple[str, str]] = []

        class Collection:
            def __init__(self, document):
                self.document = document

            async def find_one(self, query):
                return self.document

        async def get_pending_batch(
            _profile_id, batch_size, excluded_domains=None, mail_type="draft"
        ):
            pending = [
                record for record in records
                if record["sendStatus"] == "pending"
                and (
                    not excluded_domains
                    or record["email"].rsplit("@", 1)[1].casefold()
                    not in excluded_domains
                )
            ]
            return pending[:batch_size]

        async def mark_sending(email_id):
            record = next(record for record in records if record["id"] == email_id)
            if record["sendStatus"] != "pending":
                return False
            record["sendStatus"] = "sending"
            return True

        async def mark_sent(email_id, *_args, **_kwargs):
            record = next(record for record in records if record["id"] == email_id)
            record["sendStatus"] = "sent"
            sent_emails.append(record["email"])

        async def set_status(_campaign_id, status, *_args, **_kwargs):
            campaign["status"] = status.value

        async def abort_campaign(_campaign_id, reason):
            abort_calls.append((_campaign_id, reason))
            campaign["status"] = "failed"

        async def send_email(*_args, **_kwargs):
            return SimpleNamespace(
                success=True, thread_id=None, message_id="message-1", error=None
            )

        with (
            patch.object(
                worker,
                "get_collection",
                side_effect=lambda name: (
                    Collection(campaign) if name == "campaigns"
                    else Collection(profile)
                ),
            ),
            patch.object(
                worker.pe_service,
                "get_sent_domain_counts_today",
                AsyncMock(return_value={}),
            ),
            patch.object(
                worker.pe_service, "get_pending_batch", get_pending_batch
            ),
            patch.object(worker.pe_service, "mark_sending", mark_sending),
            patch.object(worker.pe_service, "mark_sent", mark_sent),
            patch.object(worker, "get_credentials_for_send", AsyncMock(return_value={
                "_id": "account-1",
                "email": "sender@example.com",
                "password": "secret",
                "smtpHost": "smtp.example.com",
                "smtpPort": 587,
                "useTls": True,
            })),
            patch.object(worker, "send_email", send_email),
            patch.object(worker, "record_send", AsyncMock()),
            patch.object(worker, "record_sent", AsyncMock()),
            patch.object(worker, "build_email_payload", lambda **_kwargs: {
                "to": "recipient@school.example",
                "subject": "Hello",
                "body": "Hello",
                "html": "Hello",
            }),
            patch.object(worker, "_push_progress", AsyncMock()),
            patch.object(worker.asyncio, "sleep", AsyncMock()),
            patch.object(
                worker.campaign_service,
                "is_worker_active",
                AsyncMock(side_effect=lambda _campaign_id: campaign["status"] in {"running", "processing"}),
            ),
            patch.object(worker.campaign_service, "abort_campaign", abort_campaign),
            patch.object(worker.campaign_service, "increment_counters", AsyncMock()),
            patch.object(
                worker.campaign_service,
                "set_status",
                side_effect=set_status,
            ),
        ):
            asyncio.run(worker._run(str(campaign_id)))

        self.assertEqual(len(sent_emails), 11)
        self.assertEqual(
            sum(email.endswith("@school.example") for email in sent_emails), 5
        )
        self.assertEqual(
            sum(email.endswith("@gmail.com") for email in sent_emails), 6
        )
        self.assertEqual(campaign["status"], "failed")
        self.assertEqual(len(abort_calls), 1)
        self.assertIn("daily limit of 5 sends", abort_calls[0][1])
        self.assertEqual(
            sum(record["sendStatus"] == "pending" for record in records), 1
        )


if __name__ == "__main__":
    unittest.main()
