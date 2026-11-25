from datetime import date, datetime, time, timedelta, timezone

from app.core.exceptions import BadRequestException


UPLOAD_DATE_PRESETS = {
    "last_30_days": 30,
    "last_3_months": 90,
}
REPLY_UPDATED_TIME_PRESETS = {
    "last_7_days": 7,
    "last_15_days": 15,
    "last_30_days": 30,
}
CUSTOM_DATE_RANGE = "custom"
UPLOAD_DATE_RANGE_VALUES = (*UPLOAD_DATE_PRESETS, CUSTOM_DATE_RANGE)


def parse_filter_date(value: date | str, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise BadRequestException(
            f"{field_name} must use DD-MM-YYYY or YYYY-MM-DD format"
        )

    normalized = value.strip()
    for date_format in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
    raise BadRequestException(
        f"{field_name} must use DD-MM-YYYY or YYYY-MM-DD format"
    )


def build_upload_date_query(
    date_range: str | None,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
    now: datetime | None = None,
) -> dict | None:
    if not date_range:
        raise BadRequestException(
            "dateRange is required when date filtering is enabled"
        )
    if date_range in UPLOAD_DATE_PRESETS:
        current_time = now or datetime.now(timezone.utc)
        return {
            "$gte": current_time
            - timedelta(days=UPLOAD_DATE_PRESETS[date_range])
        }
    if date_range != CUSTOM_DATE_RANGE:
        raise BadRequestException(
            f"dateRange must be one of {', '.join(UPLOAD_DATE_RANGE_VALUES)}"
        )

    parsed_start = (
        parse_filter_date(start_date, "startDate") if start_date is not None else None
    )
    parsed_end = (
        parse_filter_date(end_date, "endDate") if end_date is not None else None
    )
    if parsed_start and parsed_end and parsed_start > parsed_end:
        raise BadRequestException("startDate must be on or before endDate")
    if parsed_start is None and parsed_end is None:
        raise BadRequestException(
            "startDate or endDate is required when dateRange is custom"
        )

    query = {}
    if parsed_start:
        query["$gte"] = datetime.combine(
            parsed_start, time.min, tzinfo=timezone.utc
        )
    if parsed_end:
        query["$lt"] = datetime.combine(
            parsed_end + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
    return query or None
