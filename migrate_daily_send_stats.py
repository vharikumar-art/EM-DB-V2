"""
migrate_daily_send_stats.py
============================
One-time backfill migration.

Reads the existing `campaigns` collection (sent > 0) and populates
the new `daily_send_stats` collection so historical sent counts are
preserved without starting from zero.

Date attribution logic:
  1. If campaign has `completedAt`   → use that date (most accurate)
  2. Else if campaign has `startedAt`→ use that date (running/paused campaigns)
  3. Else                            → use `updatedAt` as a fallback

How to run:
  cd D:\\EmailDataBase\\email-marketing-backend\\backend
  python migrate_daily_send_stats.py

It is safe to run multiple times — upserts are idempotent.
"""

import asyncio
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

# ── Make sure app packages resolve ───────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from motor.motor_asyncio import AsyncIOMotorClient


# ─── Config — reads same .env as the FastAPI app ────────────────────────────
MONGO_URI    = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB     = os.getenv("MONGO_DB_NAME", "email_marketing_db")
COLLECTION   = "campaigns"
TARGET_COL   = "daily_send_stats"


def _pick_date(campaign: dict) -> str:
    """
    Pick the most accurate UTC date for the campaign's sent emails.

    Priority:
      1. completedAt — emails finished sending on this day
      2. startedAt   — campaign started; emails were sent from this day
      3. updatedAt   — last touched; reasonable fallback
    """
    for field in ("completedAt", "startedAt", "updatedAt"):
        val = campaign.get(field)
        if val:
            if isinstance(val, datetime):
                dt = val.replace(tzinfo=timezone.utc) if val.tzinfo is None else val
            else:
                dt = val
            return dt.strftime("%Y-%m-%d")
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def migrate():
    client = AsyncIOMotorClient(MONGO_URI)
    db     = client[MONGO_DB]
    campaigns_col = db[COLLECTION]
    stats_col     = db[TARGET_COL]

    # ── 1. Load all campaigns that actually sent at least 1 email ────────────
    cursor = campaigns_col.find({"sent": {"$gt": 0}})
    campaigns = await cursor.to_list(length=None)
    print(f"[MIGRATION] Found {len(campaigns)} campaigns with sent > 0")

    if not campaigns:
        print("[MIGRATION] Nothing to migrate. Exiting.")
        client.close()
        return

    # ── 2. Group by (employeeId, date) and sum sent counts ──────────────────
    # key → (employeeId, "YYYY-MM-DD"), value → total sent
    buckets: dict[tuple[str, str], int] = defaultdict(int)

    skipped = 0
    for c in campaigns:
        emp_id   = c.get("employeeId", "")
        sent_cnt = int(c.get("sent", 0))

        if not emp_id or sent_cnt <= 0:
            skipped += 1
            continue

        date_str = _pick_date(c)
        buckets[(emp_id, date_str)] += sent_cnt

    print(f"[MIGRATION] Built {len(buckets)} (employeeId, date) buckets "
          f"({skipped} campaigns skipped — no employeeId or 0 sent)")

    # ── 3. Upsert each bucket into daily_send_stats ──────────────────────────
    now = datetime.now(timezone.utc)
    upserted = 0
    errors   = 0

    for (emp_id, date_str), total in sorted(buckets.items()):
        try:
            await stats_col.update_one(
                {"employeeId": emp_id, "date": date_str},
                {
                    "$inc": {"sentCount": total},
                    "$set": {"updatedAt": now},
                    "$setOnInsert": {"createdAt": now},
                },
                upsert=True,
            )
            upserted += 1
            print(f"  +  {emp_id} | {date_str} | +{total} sent")
        except Exception as exc:
            errors += 1
            print(f"  X  {emp_id} | {date_str} | ERROR: {exc}")

    # ── 4. Create indexes for fast dashboard queries ─────────────────────────
    await stats_col.create_index(
        [("employeeId", 1), ("date", 1)], unique=True, name="emp_date_unique"
    )
    await stats_col.create_index([("date", 1)], name="date_idx")
    print("[MIGRATION] Indexes ensured on daily_send_stats")

    print(f"\n[MIGRATION] Done. {upserted} buckets upserted, {errors} errors.")
    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
