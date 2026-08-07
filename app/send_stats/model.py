"""
daily_send_stats model
======================
Provides a single helper to atomically increment the sent count
for a (employeeId, date) key. The collection stores one document
per employee per calendar day (UTC).

Document shape:
{
  "employeeId": "648b...",
  "date":       "2026-08-07",   # YYYY-MM-DD string — easy to filter by week/month
  "sentCount":  150,
  "updatedAt":  ISODate(...)
}
"""
from datetime import datetime, timezone

from app.database.mongodb import get_collection


async def record_sent(employee_id: str, count: int = 1) -> None:
    """
    Atomically increment sentCount for today's stat record.
    Creates the document if it does not exist (upsert).
    """
    if count <= 0:
        return

    col = get_collection("daily_send_stats")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now = datetime.now(timezone.utc)

    await col.update_one(
        {"employeeId": employee_id, "date": today_str},
        {
            "$inc": {"sentCount": count},
            "$set": {"updatedAt": now},
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
