import asyncio
from datetime import datetime, timezone
import re
from unittest.mock import patch

import pytest

from app.core.exceptions import BadRequestException
from app.email_master import router
from app.email_master.service import parse_filter_values


class FakeCursor:
    def __init__(self, docs):
        self.docs = iter(docs)

    def sort(self, *_args):
        return self

    def batch_size(self, *_args):
        return self

    async def to_list(self, length):
        batch = []
        for _ in range(length):
            try:
                batch.append(next(self.docs))
            except StopIteration:
                break
        return batch


class FakeMaster:
    def __init__(self):
        self.query = None

    def find(self, query, *_args):
        self.query = query
        return FakeCursor([
            {"email": "one@example.com", "fullName": "One"},
            {"email": "two@example.com", "fullName": "Two"},
        ])


def test_csv_download_streams_header_once_and_all_rows():
    async def run():
        with patch.object(router.service, "get_collection", return_value=FakeMaster()):
            response = await router.download_emails(
                format="csv",
                country=None,
                state=None,
                domain=None,
                university=None,
                mailSource=None,
                search=None,
                includeDuplicates=True,
                dateFilter=False,
                dateRange=None,
                startDate=None,
                endDate=None,
                current_user=None,
            )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    csv_text = asyncio.run(run())
    assert csv_text.count("fullName,email,") == 1
    assert "One,one@example.com" in csv_text
    assert "Two,two@example.com" in csv_text


def test_download_applies_custom_upload_date_filter():
    async def run():
        master = FakeMaster()
        with patch.object(router.service, "get_collection", return_value=master):
            response = await router.download_emails(
                format="csv",
                country=None,
                state=None,
                domain=None,
                university=None,
                mailSource=None,
                search=None,
                includeDuplicates=True,
                dateFilter=True,
                dateRange="custom",
                startDate="2026-03-01",
                endDate="2026-03-31",
                current_user=None,
            )
            async for _chunk in response.body_iterator:
                pass
        return master.query

    query = asyncio.run(run())
    assert query["uploadedDate"] == {
        "$gte": datetime(2026, 3, 1, tzinfo=timezone.utc),
        "$lt": datetime(2026, 4, 1, tzinfo=timezone.utc),
    }


def test_download_domain_filter_matches_domain_fields_case_insensitively():
    async def run():
        master = FakeMaster()
        with patch.object(router.service, "get_collection", return_value=master):
            response = await router.download_emails(
                format="csv",
                country=None,
                state=None,
                domain="Example.COM",
                university=None,
                mailSource=None,
                search=None,
                includeDuplicates=True,
                dateFilter=False,
                dateRange=None,
                startDate=None,
                endDate=None,
                current_user=None,
            )
            async for _chunk in response.body_iterator:
                pass
        return master.query

    query = asyncio.run(run())
    domain_regex = re.compile("^Example\\.COM$", re.IGNORECASE)
    assert query["$and"] == [
        {"$or": [{"domain": domain_regex}, {"domain_group": domain_regex}]}
    ]


def test_download_domain_filter_preserves_quoted_commas():
    async def run():
        master = FakeMaster()
        with patch.object(router.service, "get_collection", return_value=master):
            response = await router.download_emails(
                format="csv",
                country=None,
                state=None,
                domain='"ai,ml", "automation", "DL"',
                university=None,
                mailSource=None,
                search=None,
                includeDuplicates=True,
                dateFilter=False,
                dateRange=None,
                startDate=None,
                endDate=None,
                current_user=None,
            )
            async for _chunk in response.body_iterator:
                pass
        return master.query

    query = asyncio.run(run())
    expected_regexes = [
        re.compile(f"^{re.escape(value)}$", re.IGNORECASE)
        for value in ("ai,ml", "automation", "DL")
    ]
    assert query["$and"] == [
        {
            "$or": [
                {"domain": {"$in": expected_regexes}},
                {"domain_group": {"$in": expected_regexes}},
            ]
        }
    ]


def test_filter_values_split_only_unquoted_commas():
    assert parse_filter_values('"ai,ml", "automation", "DL"') == [
        "ai,ml",
        "automation",
        "DL",
    ]
    assert parse_filter_values("ai,ml,automation") == ["ai", "ml", "automation"]

    with pytest.raises(BadRequestException):
        parse_filter_values('"ai,ml')


def test_download_rejects_enabled_date_filter_without_range():
    with patch.object(router.service, "get_collection") as get_collection:
        with pytest.raises(BadRequestException):
            asyncio.run(
                router.download_emails(
                    format="csv",
                    country=None,
                    state=None,
                    domain=None,
                    university=None,
                    mailSource=None,
                    search=None,
                    includeDuplicates=True,
                    dateFilter=True,
                    dateRange=None,
                    startDate=None,
                    endDate=None,
                    current_user=None,
                )
            )

    get_collection.assert_not_called()
