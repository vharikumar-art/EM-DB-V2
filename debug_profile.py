import asyncio
import os
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

async def check_profile():
    client = AsyncIOMotorClient(os.getenv('MONGODB_URI'))
    db = client[os.getenv('MONGODB_DB', 'email_db')]
    
    # Get first profile
    profile = await db['profiles'].find_one({})
    if profile:
        print('Profile found:')
        print(f'  Name: {profile.get("profileName")}')
        print(f'  Templates: {profile.get("templates")}')
        print(f'  Old subject: {profile.get("subject")}')
        print(f'  Old body: {profile.get("body")}')
    else:
        print('No profiles found')
    
    client.close()

asyncio.run(check_profile())
