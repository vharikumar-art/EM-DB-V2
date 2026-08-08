import asyncio
import unittest
from unittest.mock import patch

from app.dashboard import service


class FakeEmployeesCollection:
    def __init__(self, docs):
        self.docs = docs

    async def find_one(self, query, *args, **kwargs):
        for doc in self.docs:
            if doc.get("userId") == query.get("userId"):
                return doc
        return None

    def find(self, query=None):
        class FakeCursor:
            def __init__(self, docs):
                self.docs = docs

            async def to_list(self, length):
                return list(self.docs)

        if query is None:
            return FakeCursor(self.docs)
        filtered = [doc for doc in self.docs if doc.get("assignedToAdmin") == query.get("assignedToAdmin")]
        return FakeCursor(filtered)


class DashboardScopeTests(unittest.TestCase):
    def test_admin_scope_includes_self_and_assigned_employees(self):
        admin_emp = {"_id": "emp1", "userId": "user1"}
        assigned_emp = {"_id": "emp2", "userId": "user2", "assignedToAdmin": "emp1"}

        def fake_get_collection(collection_name):
            if collection_name == "employees":
                return FakeEmployeesCollection([admin_emp, assigned_emp])
            raise AssertionError(f"Unexpected collection: {collection_name}")

        with patch.object(service, "get_collection", side_effect=fake_get_collection):
            scope = asyncio.run(service._resolve_dashboard_scope("admin", "user1"))

        self.assertFalse(scope["is_global"])
        self.assertEqual(scope["scope_emp_ids"], ["emp1", "emp2"])
        self.assertEqual(scope["scope_user_ids"], ["user1", "user2"])


if __name__ == "__main__":
    unittest.main()
