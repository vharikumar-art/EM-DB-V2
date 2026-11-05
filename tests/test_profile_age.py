import asyncio
from datetime import date, datetime, timezone

from app.profiles import service


def test_format_profile_age_uses_year_month_and_day_units():
    today = date(2026, 10, 28)

    assert service._format_profile_age(datetime(2026, 10, 27), today) == "1 day"
    assert service._format_profile_age(datetime(2026, 10, 18), today) == "10 days"
    assert service._format_profile_age(datetime(2026, 8, 8), today) == "2 months, 20 days"
    assert service._format_profile_age(datetime(2025, 7, 28), today) == "1 year, 3 months"


def test_format_profile_age_handles_timezone_and_missing_dates():
    today = date(2026, 10, 28)
    created_at = datetime(2026, 10, 27, 20, tzinfo=timezone.utc)

    assert service._format_profile_age(created_at, today) == "1 day"
    assert service._format_profile_age(None, today) is None


def test_format_profile_age_clamps_future_dates_to_zero():
    assert service._format_profile_age(
        datetime(2026, 10, 29), date(2026, 10, 28)
    ) == "0 days"


def test_list_profiles_includes_profile_age(monkeypatch):
    class FakeCursor:
        def sort(self, *_args):
            return self

        def __aiter__(self):
            self.documents = iter(
                [
                    {
                        "_id": "profile_1",
                        "createdAt": datetime(2026, 10, 27, tzinfo=timezone.utc),
                    }
                ]
            )
            return self

        async def __anext__(self):
            try:
                return next(self.documents)
            except StopIteration:
                raise StopAsyncIteration

    class FakeCollection:
        def find(self, _query):
            return FakeCursor()

    monkeypatch.setattr(service, "get_collection", lambda _name: FakeCollection())

    profiles = asyncio.run(service.list_profiles(None))

    assert profiles[0]["createdAt"] == "2026-10-27T00:00:00.000Z"
    assert profiles[0]["profileAge"] == "1 day"
