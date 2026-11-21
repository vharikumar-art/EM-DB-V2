from datetime import datetime, timezone

from app.database.mongodb import get_collection


async def migrate_admin_access_levels() -> int:
    """Backfill legacy admin users with the backward-compatible full access level."""
    users = get_collection("users")
    result = await users.update_many(
        {
            "role": "admin",
            "$or": [
                {"accessLevel": {"$exists": False}},
                {"accessLevel": None},
            ],
        },
        {
            "$set": {
                "accessLevel": "full",
                "updatedAt": datetime.now(timezone.utc),
            }
        },
    )
    return result.modified_count
