"""
rebuild_dropdowns.py
--------------------
Rebuilds the filter_dropdowns document from scratch by scanning
the current email_master collection.

Run after bulk deletions to remove stale country/domain/state etc. options.

Usage:
    python rebuild_dropdowns.py
"""

import asyncio
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

FILTER_DROPDOWN_ID = "global"


async def main():
    print("Connecting to MongoDB...")
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]

    master = db["email_master"]
    filter_col = db["filter_dropdowns"]
    users_col = db["users"]

    print("Scanning email_master collection...")

    # Aggregate all distinct values directly in MongoDB (efficient)
    pipeline = [
        {
            "$group": {
                "_id": None,
                "countries":     {"$addToSet": "$country"},
                "states":        {"$addToSet": "$state"},
                "universities":  {"$addToSet": "$university"},
                "designations":  {"$addToSet": "$designation"},
                "mailSources":   {"$addToSet": "$mailSource"},
                "domains":       {"$addToSet": "$domain"},
                "domain_groups": {"$addToSet": "$domain_group"},
                "uploader_ids":  {"$addToSet": "$uploadedBy"},
                "uploader_names":{"$addToSet": "$uploadedByName"},
            }
        }
    ]

    result = await master.aggregate(pipeline).to_list(1)

    if not result:
        print("No emails found in email_master. Clearing dropdowns.")
        await filter_col.replace_one(
            {"_id": FILTER_DROPDOWN_ID},
            {
                "_id": FILTER_DROPDOWN_ID,
                "countries": [], "states": [], "universities": [],
                "designations": [], "mailSources": [], "domains": [],
                "uploaders": [], "usedByEmployees": [],
                "lastUpdated": datetime.now(timezone.utc),
            },
            upsert=True,
        )
        client.close()
        return

    row = result[0]

    def clean(values: list) -> list:
        """Remove None/empty strings and sort."""
        return sorted({str(v).strip() for v in (values or []) if v and str(v).strip()})

    # Merge domain + domain_group into one list
    all_domains = clean(
        (row.get("domains") or []) + (row.get("domain_groups") or [])
    )

    # Build uploader list: pair id+name where possible
    uploader_ids   = clean(row.get("uploader_ids") or [])
    uploader_names = clean(row.get("uploader_names") or [])

    # Simple pairing: we just store unique IDs with names as best-effort
    uploaders = []
    seen_ids = set()
    async for doc in master.find({}, {"uploadedBy": 1, "uploadedByName": 1}):
        uid = str(doc.get("uploadedBy") or "").strip()
        uname = str(doc.get("uploadedByName") or "").strip()
        if uid and uid not in seen_ids:
            seen_ids.add(uid)
            uploaders.append({"id": uid, "name": uname or uid})

    new_doc = {
        "_id":          FILTER_DROPDOWN_ID,
        "countries":    clean(row.get("countries")),
        "states":       clean(row.get("states")),
        "universities": clean(row.get("universities")),
        "designations": clean(row.get("designations")),
        "mailSources":  clean(row.get("mailSources")),
        "domains":      all_domains,
        "uploaders":    uploaders,
        "usedByEmployees": [],          # rebuilt separately if needed
        "lastUpdated":  datetime.now(timezone.utc),
    }

    # Print summary before saving
    print(f"\n  Countries   : {len(new_doc['countries'])}")
    print(f"  States      : {len(new_doc['states'])}")
    print(f"  Universities: {len(new_doc['universities'])}")
    print(f"  Designations: {len(new_doc['designations'])}")
    print(f"  Mail Sources: {len(new_doc['mailSources'])}")
    print(f"  Domains     : {len(new_doc['domains'])}")
    print(f"  Uploaders   : {len(new_doc['uploaders'])}")

    # Full replace (not addToSet) so stale values are removed
    await filter_col.replace_one(
        {"_id": FILTER_DROPDOWN_ID},
        new_doc,
        upsert=True,
    )

    print("\nDONE: filter_dropdowns rebuilt successfully from current email_master data.")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
