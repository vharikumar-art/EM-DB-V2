"""Simple cleanup - run via Python directly"""
import asyncio
import sys
sys.path.insert(0, '.')

from app.database.mongodb import connect_to_mongo, close_mongo_connection, get_collection

async def cleanup():
    await connect_to_mongo()
    
    try:
        profiles_col = get_collection('profiles')
        profile_emails_col = get_collection('profile_emails')
        email_master_col = get_collection('email_master')
        
        print("=" * 60)
        print("🧹 EMAIL MARKETING BACKEND - FULL CLEANUP")
        print("=" * 60)
        
        # ========== CLEANUP 1: Orphaned Profile Emails ==========
        print("\n📋 STEP 1: Removing orphaned profile_emails records")
        print("-" * 60)
        
        profile_ids_in_emails = await profile_emails_col.distinct('profileId')
        print(f"Found {len(profile_ids_in_emails)} unique profileIds in profile_emails\n")
        
        orphaned_count = 0
        deleted_records = 0
        
        for profile_id in profile_ids_in_emails:
            profile_exists = await profiles_col.find_one({'_id': profile_id})
            
            if not profile_exists:
                orphaned_count += 1
                result = await profile_emails_col.delete_many({'profileId': profile_id})
                deleted_records += result.deleted_count
                print(f"  ❌ Profile {profile_id}: Deleted {result.deleted_count} orphaned emails")
        
        print(f"\n✅ Orphaned profile_emails cleanup complete!")
        print(f"   Orphaned profiles found: {orphaned_count}")
        print(f"   Orphaned emails deleted: {deleted_records}")
        
        # ========== CLEANUP 2: Email Master ==========
        print("\n📋 STEP 2: Clearing Email Master")
        print("-" * 60)
        
        master_count_before = await email_master_col.count_documents({})
        print(f"Emails in Email Master: {master_count_before}")
        
        if master_count_before > 0:
            result = await email_master_col.delete_many({})
            print(f"Deleted: {result.deleted_count} emails from Email Master")
        else:
            print("Email Master is already empty")
        
        master_count_after = await email_master_col.count_documents({})
        
        # ========== FINAL STATS ==========
        print("\n" + "=" * 60)
        print("📊 FINAL DATABASE STATS")
        print("=" * 60)
        
        total_profiles = await profiles_col.count_documents({})
        total_emails = await profile_emails_col.count_documents({})
        total_pending = await profile_emails_col.count_documents({'sendStatus': 'pending'})
        total_master = await email_master_col.count_documents({})
        
        print(f"\n✅ Profiles collection: {total_profiles} records")
        print(f"✅ Profile_emails collection: {total_emails} records")
        print(f"   └─ Pending: {total_pending}")
        print(f"✅ Email_master collection: {total_master} records (cleared)")
        
        print("\n" + "=" * 60)
        print("🎉 CLEANUP COMPLETE!")
        print("=" * 60)
        print(f"\nSummary:")
        print(f"  • Removed {deleted_records} orphaned profile_emails")
        print(f"  • Cleared {master_count_before} emails from Email Master")
        print(f"  • Database ready for fresh start ✅")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await close_mongo_connection()

if __name__ == '__main__':
    print("\n🧹 Starting full cleanup...\n")
    asyncio.run(cleanup())
