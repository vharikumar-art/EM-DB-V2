"""
Reset Database Script
Clears ALL collections EXCEPT users collection
Keeps all user accounts intact
"""

import asyncio
import sys
sys.path.insert(0, '.')

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
        print("🧹 Database Reset - Clearing all collections except 'users'\n")
        
        total_deleted = 0
        
        for collection_name in collections_to_clear:
            col = get_collection(collection_name)
            count = await col.count_documents({})
            
            if count > 0:
                result = await col.delete_many({})
                total_deleted += result.deleted_count
                print(f"✅ {collection_name}: Deleted {result.deleted_count} records")
            else:
                print(f"⏭️  {collection_name}: Already empty")
        
        # Verify users collection still exists
        users_col = get_collection('users')
        user_count = await users_col.count_documents({})
        
        print(f"\n📊 Summary:")
        print(f"   Total records deleted: {total_deleted}")
        print(f"   Users preserved: {user_count} ✅")
        print(f"\n✅ Database reset complete!")
        print(f"   All data cleared except user accounts")
        print(f"   Users can login and start fresh")
        
    except Exception as e:
        print(f"❌ Error during reset: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await close_mongo_connection()

if __name__ == '__main__':
    print("=" * 60)
    print("DATABASE RESET TOOL")
    print("=" * 60)
    print("\n⚠️  WARNING: This will clear all data except user accounts!")
    print("   - Email Master (uploaded emails)")
    print("   - Profiles (campaign templates)")
    print("   - Profile Emails (email queues)")
    print("   - Campaigns (active sends)")
    print("   - Email Accounts (SMTP credentials)")
    print("   - All logs and notifications")
    print("\n✅ PRESERVED:")
    print("   - User accounts (can still login)")
    print("\n" + "=" * 60)
    
    response = input("\n🤔 Are you sure? Type 'YES' to confirm: ")
    
    if response.strip().upper() == 'YES':
        print("\n🧹 Starting reset...\n")
        asyncio.run(reset_database())
    else:
        print("\n❌ Reset cancelled - no changes made")
