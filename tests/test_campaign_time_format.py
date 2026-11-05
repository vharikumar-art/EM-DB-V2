from datetime import datetime, timedelta, timezone

from app.campaigns.service import _serialize_campaign
from app.campaigns.time_format import (
    format_campaign_time_12_hour,
    format_utc_datetime_12_hour,
)


def test_format_campaign_time_uses_12_hour_clock():
    assert format_campaign_time_12_hour("2026-11-05T00:05") == "2026-11-05 12:05 AM"
    assert format_campaign_time_12_hour("2026-11-05T12:05") == "2026-11-05 12:05 PM"
    assert format_campaign_time_12_hour("13:05") == "1:05 PM"


def test_format_utc_datetime_uses_12_hour_clock_and_utc():
    local_time = datetime(
        2026, 11, 5, 18, 35, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )

    assert format_utc_datetime_12_hour(local_time) == "2026-11-05 1:05 PM UTC"


def test_campaign_response_formats_display_copy_without_changing_schedule_data():
    scheduled_display = "2026-11-05T00:05"
    scheduled_for = datetime(2026, 11, 4, 18, 35, tzinfo=timezone.utc)
    document = {
        "scheduledForDisplay": scheduled_display,
        "scheduledFor": scheduled_for,
        "startedAt": datetime(2026, 11, 5, 0, 5, tzinfo=timezone.utc),
    }

    response = _serialize_campaign(document)

    assert response["scheduledForDisplay"] == "2026-11-05 12:05 AM"
    assert response["scheduledFor"] == "2026-11-04T18:35:00.000Z"
    assert response["startedAtDisplay"] == "2026-11-05 12:05 AM UTC"
    assert document["scheduledForDisplay"] == scheduled_display
    assert document["scheduledFor"] == scheduled_for
