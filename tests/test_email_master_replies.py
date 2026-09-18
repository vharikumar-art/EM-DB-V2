import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from bson import ObjectId
from pydantic import ValidationError

from app.email_master import service
from app.email_master.schema import MarkReplyRequest, UpdateReplyRequest
from app.schemas.common import PaginationParams


class FakeUpdateResult:
    def __init__(self, matched_count):
        self.matched_count = matched_count


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *args, **kwargs):
        return self

    def skip(self, amount):
        self.documents = self.documents[amount:]
        return self

    def limit(self, amount):
        self.documents = self.documents[:amount]
        return self

    def __aiter__(self):
        self.iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents

    @staticmethod
    def matches(document, query):
        for key, expected in query.items():
            actual = document.get(key)
            if isinstance(expected, dict) and "$regex" in expected:
                import re
                if not re.search(expected["$regex"], actual or "", re.IGNORECASE):
                    return False
            elif isinstance(expected, dict) and expected.get("$ne") is not None:
                if actual == expected["$ne"]:
                    return False
            elif actual != expected:
                return False
        return True

    async def update_many(self, query, update):
        matches = [doc for doc in self.documents if self.matches(doc, query)]
        for doc in matches:
            doc.update(update["$set"])
        return FakeUpdateResult(len(matches))

    async def delete_many(self, query):
        matches = [doc for doc in self.documents if self.matches(doc, query)]
        return type("DeleteResult", (), {"deleted_count": len(matches)})()

    async def find_one(self, query, sort=None):
        for doc in self.documents:
            if self.matches(doc, query):
                return doc
        return None

    async def count_documents(self, query):
        return sum(self.matches(doc, query) for doc in self.documents)

    def find(self, query, projection=None):
        return FakeCursor(
            [doc for doc in self.documents if self.matches(doc, query)]
        )

    async def find_one_and_update(self, query, update, return_document=True):
        for doc in self.documents:
            if self.matches(doc, query):
                doc.update(update["$set"])
                return doc
        return None


class EmailMasterReplyTests(unittest.TestCase):
    def test_other_reason_requires_custom_reason(self):
        with self.assertRaises(ValidationError):
            MarkReplyRequest(email="client@example.com", reason="other")

        request = MarkReplyRequest(
            email="client@example.com",
            reason="other",
            customReason="Asked for a proposal",
        )
        self.assertEqual(request.customReason, "Asked for a proposal")

    def test_mark_reply_saves_custom_reason(self):
        document = {"_id": ObjectId(), "email": "client@example.com", "hasReply": False}
        collection = FakeCollection([document])

        with patch.object(service, "get_collection", return_value=collection):
            result = asyncio.run(
                service.mark_email_reply(
                    email="client@example.com",
                    reason="other",
                    custom_reason="Asked for a proposal",
                    marked_by="user-1",
                )
            )

        self.assertTrue(result["hasReply"])
        self.assertEqual(result["replyReason"], "other")
        self.assertEqual(result["replyCustomReason"], "Asked for a proposal")
        self.assertEqual(result["replyMarkedBy"], "user-1")
        self.assertEqual(result["replyMarkedByName"], "user-1")

    def test_list_replies_returns_only_marked_records(self):
        documents = [
            {"_id": ObjectId(), "email": "replied@example.com", "hasReply": True},
            {"_id": ObjectId(), "email": "pending@example.com", "hasReply": False},
        ]
        collection = FakeCollection(documents)

        with patch.object(service, "get_collection", return_value=collection):
            result = asyncio.run(
                service.list_email_replies(PaginationParams(page=1, pageSize=25))
            )

        self.assertEqual(result["data"][0]["email"], "replied@example.com")
        self.assertEqual(result["replyCount"], 1)
        self.assertEqual(result["convertedCount"], 0)
        self.assertEqual(result["otherCount"], 0)
        self.assertEqual(result["total"], 1)

    def test_list_replies_resolves_marker_name_when_stored_value_is_id(self):
        marker_id = str(ObjectId())
        documents = [
            {
                "_id": ObjectId(),
                "email": "replied@example.com",
                "hasReply": True,
                "replyMarkedBy": marker_id,
                "replyMarkedByName": marker_id,
            }
        ]
        collection = FakeCollection(documents)

        with patch.object(service, "get_collection", return_value=collection), patch.object(
            service, "get_user_display_name", return_value="VHK"
        ):
            result = asyncio.run(
                service.list_email_replies(PaginationParams(page=1, pageSize=25))
            )

        self.assertEqual(result["data"][0]["replyMarkedByName"], "VHK")

    def test_display_name_resolves_employee_id(self):
        employee_id = ObjectId()
        user_id = ObjectId()
        users = FakeCollection([{"_id": user_id, "name": "Muhamad Ali"}])
        employees = FakeCollection([{"_id": employee_id, "userId": str(user_id)}])

        def get_collection(name):
            return users if name == "users" else employees

        with patch.object(service, "get_collection", side_effect=get_collection):
            result = asyncio.run(service.get_user_display_name(str(employee_id)))

        self.assertEqual(result, "Muhamad Ali")

    def test_update_reply_can_clear_status(self):
        document = {
            "_id": ObjectId(),
            "email": "client@example.com",
            "hasReply": True,
            "replyReason": "converted",
            "replyMarkedAt": datetime.now(timezone.utc),
        }
        collection = FakeCollection([document])

        with patch.object(service, "get_collection", return_value=collection):
            result = asyncio.run(
                service.update_email_reply(
                    email_id=str(document["_id"]),
                    payload={"hasReply": False},
                    marked_by="user-1",
                )
            )

        self.assertFalse(result["hasReply"])
        self.assertIsNone(result["replyReason"])
        self.assertIsNone(result["replyMarkedAt"])

if __name__ == "__main__":
    unittest.main()
