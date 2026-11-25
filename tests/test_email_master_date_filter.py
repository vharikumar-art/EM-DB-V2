import asyncio
import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

from app.email_master import service
from app.email_master.router import list_emails
from app.core.exceptions import BadRequestException
from app.email_master.date_filters import build_upload_date_query
from app.schemas.common import PaginationParams


class EmptyCursor:
    def sort(self, *args, **kwargs):
        return self

    def skip(self, amount):
        return self

    def limit(self, amount):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class RangeCollection:
    def __init__(self):
        self.query = None

    async def count_documents(self, query):
        self.query = query
        return 0

    def find(self, query):
        self.query = query
        return EmptyCursor()


class EmailMasterDateFilterTests(unittest.TestCase):
    def test_upload_date_presets_use_shared_windows(self):
        now = datetime(2026, 3, 31, 12, tzinfo=timezone.utc)

        self.assertEqual(
            build_upload_date_query("last_30_days", now=now),
            {"$gte": now - timedelta(days=30)},
        )
        self.assertEqual(
            build_upload_date_query("last_3_months", now=now),
            {"$gte": now - timedelta(days=90)},
        )

    def test_profile_custom_date_range_accepts_both_formats_and_includes_end_day(self):
        query = build_upload_date_query(
            "custom",
            "01-03-2026",
            "2026-03-31",
        )

        self.assertEqual(
            query,
            {
                "$gte": datetime(2026, 3, 1, tzinfo=timezone.utc),
                "$lt": datetime(2026, 4, 1, tzinfo=timezone.utc),
            },
        )

    def test_invalid_profile_date_filter_fails_instead_of_being_ignored(self):
        class CountCollection:
            count_called = False

            async def count_documents(self, _query):
                self.count_called = True
                return 0

        collection = CountCollection()
        with patch.object(service, "get_collection", return_value=collection):
            with self.assertRaises(BadRequestException):
                asyncio.run(
                    service.count_filtered_emails(
                        {
                            "date_filter": True,
                            "date_range": "custom",
                            "start_date": "2026-02-31",
                        }
                    )
                )

        self.assertFalse(collection.count_called)

    def test_custom_range_requires_at_least_one_date(self):
        with self.assertRaises(BadRequestException):
            build_upload_date_query("custom")

    def test_enabled_date_filter_requires_a_preset(self):
        class CountCollection:
            async def count_documents(self, _query):
                raise AssertionError("Invalid date filters must fail before querying")

        with patch.object(
            service, "get_collection", return_value=CountCollection()
        ):
            with self.assertRaises(BadRequestException):
                asyncio.run(
                    service.count_filtered_emails({"date_filter": True})
                )

    def test_custom_range_requires_valid_ordered_dates(self):
        requests = (
            {"dateFilter": True, "dateRange": "custom", "startDate": "2026-03-01"},
            {
                "dateFilter": True,
                "dateRange": "custom",
                "startDate": "2026-04-01",
                "endDate": "2026-03-31",
            },
            {"dateFilter": True, "dateRange": "unknown"},
        )
        common_params = {
            "country": [],
            "state": [],
            "domain": [],
            "university": [],
            "uploadedBy": [],
            "usedByEmployee": [],
            "mailSource": [],
            "search": None,
            "includeDuplicates": True,
            "dateFilter": False,
            "dateRange": None,
            "startDate": None,
            "endDate": None,
            "params": PaginationParams(),
            "current_user": object(),
        }

        for date_params in requests:
            with self.subTest(date_params=date_params):
                with self.assertRaises(BadRequestException):
                    asyncio.run(list_emails(**{**common_params, **date_params}))

    def test_custom_range_includes_the_entire_end_date(self):
        collection = RangeCollection()

        async def unchanged(docs):
            return docs

        with (
            patch.object(service, "get_collection", return_value=collection),
            patch.object(service, "_enrich_emails_with_profile_names", unchanged),
            patch.object(service, "_enrich_emails_with_employee_names", unchanged),
        ):
            asyncio.run(
                service.list_emails(
                    PaginationParams(),
                    date_filter=True,
                    date_range="custom",
                    start_date=date(2026, 3, 1),
                    end_date=date(2026, 3, 31),
                )
            )

        self.assertEqual(
            collection.query["uploadedDate"],
            {
                "$gte": datetime(2026, 3, 1, tzinfo=timezone.utc),
                "$lt": datetime.combine(
                    date(2026, 3, 31) + timedelta(days=1),
                    time.min,
                    tzinfo=timezone.utc,
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
