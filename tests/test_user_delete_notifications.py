import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.users import service


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents

    async def find_one(self, query, projection=None):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                return document
        return None

    async def delete_one(self, query):
        for index, document in enumerate(self.documents):
            if document.get("_id") == query.get("_id"):
                self.documents.pop(index)
                return type("DeleteResult", (), {"deleted_count": 1})()
        return type("DeleteResult", (), {"deleted_count": 0})()

    async def delete_many(self, query):
        self.documents[:] = [
            document
            for document in self.documents
            if document.get("userId") != query.get("userId")
        ]


class UserDeleteNotificationTests(unittest.TestCase):
    def test_delete_user_notifies_before_employee_cascade(self):
        user_id = ObjectId()
        employee_id = ObjectId()
        users = FakeCollection([
            {"_id": user_id, "name": "Deleted User", "email": "deleted@example.com"}
        ])
        employees = FakeCollection([
            {"_id": employee_id, "userId": str(user_id), "assignedToAdmin": "admin-1"}
        ])
        notification = AsyncMock()

        def get_collection(name):
            return users if name == "users" else employees

        with patch.object(service, "get_collection", side_effect=get_collection), patch(
            "app.notifications.service.create_notification", notification
        ):
            asyncio.run(service.delete_user(str(user_id), actor_role="admin"))

        notification.assert_awaited_once()
        args = notification.await_args.args
        self.assertEqual(args[0], str(employee_id))
        self.assertEqual(args[1], "User Deleted User was deleted.")
        self.assertEqual(args[2].value, "info")
        self.assertEqual(len(users.documents), 0)
        self.assertEqual(len(employees.documents), 0)


if __name__ == "__main__":
    unittest.main()
