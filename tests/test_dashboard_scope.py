import asyncio
import unittest
from datetime import datetime, timezone
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
            if collection_name == "users":
                from unittest.mock import AsyncMock, MagicMock
                users_mock = MagicMock()
                users_mock.find_one = AsyncMock(return_value={"accessLevel": "partial"})
                return users_mock
            raise AssertionError(f"Unexpected collection: {collection_name}")

        with patch.object(service, "get_collection", side_effect=fake_get_collection):
            scope = asyncio.run(service._resolve_dashboard_scope("admin", "user1"))

        self.assertFalse(scope["is_global"])
        self.assertEqual(scope["scope_emp_ids"], ["emp1", "emp2"])
        self.assertEqual(scope["scope_user_ids"], ["user1", "user2"])

    def test_current_week_range_uses_monday_to_sunday(self):
        now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

        week_start, week_end = service._get_current_week_range(now)

        self.assertEqual(week_start.strftime("%Y-%m-%d"), "2026-09-07")
        self.assertEqual(week_end.strftime("%Y-%m-%d"), "2026-09-13")

    def test_last_week_range_uses_previous_monday_to_sunday(self):
        now = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)

        week_start, week_end = service._get_last_week_range(now)

        self.assertEqual(week_start.strftime("%Y-%m-%d"), "2026-08-31")
        self.assertEqual(week_end.strftime("%Y-%m-%d"), "2026-09-06")

    def test_current_office_month_after_26th_runs_through_next_month_25th(self):
        now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

        month_start, month_end = service._get_current_month_range(now)

        self.assertEqual(month_start.strftime("%Y-%m-%d"), "2026-10-26")
        self.assertEqual(month_end.strftime("%Y-%m-%d"), "2026-11-25")

    def test_current_office_month_on_or_before_25th_starts_previous_month_26th(self):
        now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

        month_start, month_end = service._get_current_month_range(now)

        self.assertEqual(month_start.strftime("%Y-%m-%d"), "2026-09-26")
        self.assertEqual(month_end.strftime("%Y-%m-%d"), "2026-10-25")

    def test_current_office_month_handles_year_boundary(self):
        now = datetime(2026, 12, 30, 12, 0, tzinfo=timezone.utc)

        month_start, month_end = service._get_current_month_range(now)

        self.assertEqual(month_start.strftime("%Y-%m-%d"), "2026-12-26")
        self.assertEqual(month_end.strftime("%Y-%m-%d"), "2027-01-25")

    def test_last_office_month_is_previous_26th_through_25th(self):
        now = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)

        month_start, month_end = service._get_last_month_range(now)

        self.assertEqual(month_start.strftime("%Y-%m-%d"), "2026-09-26")
        self.assertEqual(month_end.strftime("%Y-%m-%d"), "2026-10-25")

    def test_last_office_month_handles_year_boundary(self):
        now = datetime(2027, 1, 10, 12, 0, tzinfo=timezone.utc)

        month_start, month_end = service._get_last_month_range(now)

        self.assertEqual(month_start.strftime("%Y-%m-%d"), "2026-11-26")
        self.assertEqual(month_end.strftime("%Y-%m-%d"), "2026-12-25")


if __name__ == "__main__":
    unittest.main()
