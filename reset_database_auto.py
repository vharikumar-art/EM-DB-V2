"""
Auto Reset Database Script (No User Confirmation)
Clears ALL collections EXCEPT users collection
"""

import asyncio
import sys
import os
sys.path.insert(0, '.')

# Fix Unicode encoding for Windows
os.environ['PYTHONIOENCODING'] = 'utf-8'

from app.database.mongodb import connect_to_mongo, close_mongo_connection, get_collection

async def reset_database():
    """Clear all collections except users"""
    await connect_to_mongo()
    
    collections_to_clear = [
        'email_master',
        'profiles',
        'profile_emails',
        'campaigns',
        'email_accounts',
        'employees',
        'campaign_logs',
        'logs',
        'notifications',
        'templates',
    ]
    
    try:
        print("Database Reset - Clearing all collections except 'users'\n")
        
        total_deleted = 0
        
        for collection_name in collections_to_clear:
            col = get_collection(collection_name)
            count = await col.count_documents({})
            
            if count > 0:
                result = await col.delete_many({})
                total_deleted += result.deleted_count
                print(f"[OK] {collection_name}: Deleted {result.deleted_count} records")
            else:
                print(f"[SKIP] {collection_name}: Already empty")
        
        # Verify users collection still exists
        users_col = get_collection('users')
        user_count = await users_col.count_documents({})
        
        print(f"\nSummary:")
        print(f"   Total records deleted: {total_deleted}")
        print(f"   Users preserved: {user_count} [OK]")
        print(f"\nDatabase reset complete!")
        print(f"   All data cleared except user accounts")
        print(f"   Users can login and start fresh")
        
    except Exception as e:
        print(f"ERROR during reset: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await close_mongo_connection()

if __name__ == '__main__':
    print("=" * 60)
    print("DATABASE RESET - AUTO MODE")
    print("=" * 60)
    print("\nClearing all collections except 'users'...\n")
    asyncio.run(reset_database())
