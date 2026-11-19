import asyncio
import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

from app.email_master import service
from app.email_master.router import list_emails
from app.core.exceptions import BadRequestException
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
