"""
One-time migration script: Backfill usageCount, usedByEmployeeIds, usedByEmployeeNames
for existing email_master documents that predate the usage-tracking feature.

HOW TO RUN:
    cd d:\EmailDataBase\email-marketing-backend\backend
    python migrate_email_usage.py

This script is SAFE to run multiple times (idempotent).
It only updates documents that have NOT yet been migrated.
"""

import asyncio
import os
from pathlib import Path
from motor.motor_asyncio import AsyncIOMotorClient

# ── Load from .env file automatically ────────────────────────────────────────
_env_file = Path(__file__).resolve().parent / ".env"
_env_vars: dict = {}
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            _env_vars[key.strip()] = val.strip()

MONGO_URI  = _env_vars.get("MONGO_URI", os.environ.get("MONGO_URI", "mongodb://localhost:27017"))
DB_NAME    = _env_vars.get("MONGO_DB_NAME", os.environ.get("MONGO_DB_NAME", "email_marketing_db"))
COLLECTION = "email_master"

print(f"Connecting to DB: {DB_NAME}")
# ─────────────────────────────────────────────────────────────────────────────


async def migrate():
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    col = db[COLLECTION]

    print("=" * 60)
    print("Email Master — Usage Tracking Backfill Migration")
    print("=" * 60)

    # Count how many docs need migration
    total_docs = await col.count_documents({})
    already_migrated = await col.count_documents({"usageCount": {"$exists": True}})
    to_migrate = total_docs - already_migrated

    print(f"  Total documents  : {total_docs}")
    print(f"  Already migrated : {already_migrated}")
    print(f"  Need migration   : {to_migrate}")
    print()

    if to_migrate == 0:
        print("Nothing to migrate. All documents already have usageCount.")
        client.close()
        return

    updated = 0

    # Process only docs that don't have usageCount yet
    cursor = col.find({"usageCount": {"$exists": False}})

    async for doc in cursor:
        doc_id = doc["_id"]

        # ── Compute usageCount ────────────────────────────────────────────
        used_in_profiles = doc.get("usedInProfiles", [])  # list of {profileId, employeeId, usedDate}
        usage_count = len(used_in_profiles)

        # Also consider old single-field: if inProfileEmails is True and no usedInProfiles,
        # it was used at least once.
        if usage_count == 0 and doc.get("inProfileEmails", False):
            usage_count = 1

        # ── Compute usedByEmployeeIds / usedByEmployeeNames ───────────────
        employee_ids: list = []
        employee_names: list = []

        # From old single-value fields
        old_id   = doc.get("usedByEmployeeId")
        old_name = doc.get("usedByEmployeeName")
        if old_id and str(old_id) not in employee_ids:
            employee_ids.append(str(old_id))
            employee_names.append(old_name or str(old_id))

        # From usedInProfiles list
        for profile_entry in used_in_profiles:
            emp_id = profile_entry.get("employeeId")
            if emp_id and str(emp_id) not in employee_ids:
                employee_ids.append(str(emp_id))
                employee_names.append(str(emp_id))  # name unknown from this record, use ID

        # ── Build update ──────────────────────────────────────────────────
        update = {
            "$set": {
                "usageCount":          usage_count,
                "usedByEmployeeIds":   employee_ids,
                "usedByEmployeeNames": employee_names,
            }
        }

        await col.update_one({"_id": doc_id}, update)
        updated += 1

        if updated % 500 == 0:
            print(f"  Progress: {updated}/{to_migrate} migrated...")

    print()
    print(f"Migration complete! Updated: {updated}")
    print()
    print("Summary of migrated state:")
    fresh      = await col.count_documents({"usageCount": 0})
    used_once  = await col.count_documents({"usageCount": 1})
    used_multi = await col.count_documents({"usageCount": {"$gt": 1}})
    locked     = await col.count_documents({"inProfileEmails": True})
    print(f"  Fresh (usageCount=0)   : {fresh}")
    print(f"  Used once              : {used_once}")
    print(f"  Used multiple times    : {used_multi}")
    print(f"  Currently locked       : {locked}  (inProfileEmails=True, in an active profile)")

    client.close()


if __name__ == "__main__":
    asyncio.run(migrate())
