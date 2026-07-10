import asyncio
from app.database.mongodb import connect_to_mongo, close_mongo_connection, get_database


async def main() -> None:
    await connect_to_mongo()
    db = get_database()
    names = await db.list_collection_names()
    for name in names:
        await db[name].drop()
    print(f"Dropped collections: {names if names else 'none'}")
    await close_mongo_connection()


asyncio.run(main())
