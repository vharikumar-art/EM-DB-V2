from datetime import datetime, time, timedelta, timezone

from app.core.exceptions import BadRequestException
from app.dashboard.schema import DashboardQuery, DateRangePreset


def resolve_date_range(query: DashboardQuery) -> tuple[datetime, datetime]:
    """Returns (start_datetime, end_datetime) in UTC, end being exclusive-ish (end of day)."""
    now = datetime.now(timezone.utc)
    today = now.date()

    if query.preset == DateRangePreset.TODAY:
        start_date, end_date = today, today
    elif query.preset == DateRangePreset.YESTERDAY:
        yesterday = today - timedelta(days=1)
        start_date, end_date = yesterday, yesterday
    elif query.preset == DateRangePreset.LAST_7_DAYS:
        start_date, end_date = today - timedelta(days=6), today
    elif query.preset == DateRangePreset.LAST_MONTH:
        start_date, end_date = today - timedelta(days=30), today
    else:  # CUSTOM
        if not query.startDate or not query.endDate:
            raise BadRequestException("startDate and endDate are required for a custom range")
        if query.startDate > query.endDate:
            raise BadRequestException("startDate must be before endDate")
        start_date, end_date = query.startDate, query.endDate

    start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)
    return start_dt, end_dt
