"""
Migration script to add branch field to all existing users
Sets all branches to "Vellore"
Run: python -m migrate_add_branch
"""
import sys
import asyncio
sys.path.insert(0, '/path/to/backend')

from app.database.mongodb import get_collection


async def migrate():
    users = get_collection("users")
    result = await users.update_many({}, {"$set": {"branch": "Vellore"}})
    print(f"✅ Updated {result.modified_count} users - branch set to 'Vellore'")


if __name__ == "__main__":
    asyncio.run(migrate())
