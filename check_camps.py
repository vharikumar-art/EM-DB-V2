import asyncio
from datetime import datetime, timezone, timedelta

async def check():
    from app.database.mongodb import connect_to_mongo
    from app.database.mongodb import get_collection

    await connect_to_mongo()
    col = get_collection('campaigns')

    cursor = col.find()
    docs = await cursor.to_list(length=None)

    for doc in docs:
        print(f"Name: {doc.get('campaignName')} - Status: {doc.get('status')} - ScheduledFor: {doc.get('scheduledFor')} - CreatedAt: {doc.get('createdAt')}")

asyncio.run(check())
