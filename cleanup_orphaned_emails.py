"""
Cleanup script to remove orphaned profile_emails records.

Orphaned records: profile_emails rows where the profile_id no longer exists in profiles collection.

This script:
1. Finds all unique profileIds in profile_emails
2. Checks which ones don't exist in profiles collection
3. Deletes those orphaned records
4. Reports how many were deleted
"""

import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URL = os.getenv('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.getenv('MONGO_DB', 'email_marketing')


async def cleanup_orphaned_emails():
    """Remove profile_emails records whose profileId doesn't exist in profiles."""
    
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]
    
    try:
        profiles_col = db['profiles']
        profile_emails_col = db['profile_emails']
        
        # Get all unique profileIds from profile_emails
        orphaned_pipeline = [
            {
                '$group': {
                    '_id': '$profileId'
                }
            }
        ]
        
        all_profile_ids = await profile_emails_col.aggregate(orphaned_pipeline).to_list(None)
        print(f"Found {len(all_profile_ids)} unique profileIds in profile_emails")
        
        # Check which profiles actually exist
        orphaned_count = 0
        deleted_records = 0
        
        for item in all_profile_ids:
            profile_id = item['_id']
            profile_exists = await profiles_col.find_one({'_id': profile_id})
            
            if not profile_exists:
                # This profile doesn't exist - delete all its emails
                orphaned_count += 1
                result = await profile_emails_col.delete_many({'profileId': profile_id})
                deleted_records += result.deleted_count
                print(f"  ❌ Deleted {result.deleted_count} orphaned emails for profile {profile_id}")
        
        print(f"\n✅ Cleanup complete!")
        print(f"   - Orphaned profiles found: {orphaned_count}")
        print(f"   - Orphaned emails deleted: {deleted_records}")
        
        # Show updated stats
        total_pending = await profile_emails_col.count_documents({'sendStatus': 'pending'})
        total_emails = await profile_emails_col.count_documents({})
        print(f"\n📊 Updated stats:")
        print(f"   - Total profile_emails: {total_emails}")
        print(f"   - Pending: {total_pending}")
        
    except Exception as e:
        print(f"❌ Error during cleanup: {str(e)}")
    finally:
        client.close()


if __name__ == '__main__':
    print("🧹 Email Marketing Backend - Orphaned Records Cleanup\n")
    asyncio.run(cleanup_orphaned_emails())
