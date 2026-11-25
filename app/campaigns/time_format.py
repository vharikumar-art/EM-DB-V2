from datetime import datetime, time, timezone


def format_campaign_time_12_hour(value: str) -> str:
    try:
        parsed_datetime = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed_time = time.fromisoformat(value)
        except ValueError:
            return value
        hour = parsed_time.hour % 12 or 12
        return f"{hour}:{parsed_time.minute:02d} {parsed_time.strftime('%p')}"

    return (
        f"{parsed_datetime.date().isoformat()} "
        f"{parsed_datetime.hour % 12 or 12}:{parsed_datetime.minute:02d} "
        f"{parsed_datetime.strftime('%p')}"
    )


def format_utc_datetime_12_hour(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return (
        f"{value.date().isoformat()} "
        f"{value.hour % 12 or 12}:{value.minute:02d} "
        f"{value.strftime('%p')} UTC"
    )
