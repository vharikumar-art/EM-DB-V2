"""
Quick Fix Script - Reschedule Past Campaigns to the Future

This script finds all campaigns that have scheduledFor times in the PAST
and reschedules them to 5 minutes from now.

Usage:
    python fix_scheduled_campaigns.py
"""

import asyncio
from datetime import datetime, timedelta, timezone
from app.database.mongodb import connect_to_mongo, close_mongo_connection, get_collection


async def fix_scheduled_campaigns():
    """Find and fix campaigns scheduled in the past"""
    
    try:
        await connect_to_mongo()
        campaigns_col = get_collection("campaigns")
        
        now = datetime.now(timezone.utc)
        future_time = now + timedelta(minutes=5)
        
        print("=" * 70)
        print("SCHEDULER FIX - Reschedule Past Campaigns")
        print("=" * 70)
        print()
        
        print(f"Current UTC time: {now.isoformat()}")
        print(f"New scheduled time: {future_time.isoformat()}")
        print()
        
        # Find campaigns with past scheduledFor times
        past_campaigns = await campaigns_col.find({
            "status": "scheduled",
            "scheduledFor": {"$lt": now}
        }).to_list(length=None)
        
        if not past_campaigns:
            print("✅ No campaigns with past scheduled times found!")
            print()
            return
        
        print(f"Found {len(past_campaigns)} campaign(s) with past scheduled times:")
        print()
        
        for campaign in past_campaigns:
            campaign_id = str(campaign["_id"])
            campaign_name = campaign.get("campaignName", "Unknown")
            scheduled_for = campaign.get("scheduledFor")
            
            print(f"Campaign: {campaign_name}")
            print(f"  ID: {campaign_id}")
            print(f"  Current scheduledFor: {scheduled_for}")
            print(f"  Status: {campaign.get('status')}")
            print()
        
        # Ask for confirmation
        response = input(f"Reschedule these {len(past_campaigns)} campaign(s) to {future_time.isoformat()}? (yes/no): ")
        
        if response.lower() != "yes":
            print("❌ Cancelled. No changes made.")
            return
        
        # Update campaigns
        result = await campaigns_col.update_many(
            {
                "status": "scheduled",
                "scheduledFor": {"$lt": now}
            },
            {
                "$set": {
                    "scheduledFor": future_time,
                    "updatedAt": now
                }
            }
        )
        
        print()
        print("=" * 70)
        print(f"✅ Updated {result.modified_count} campaign(s)")
        print("=" * 70)
        print()
        print("Next steps:")
        print("1. Wait for next minute")
        print("2. Watch the logs: tail -f /var/log/syslog | grep campaign-scheduler")
        print("3. Campaigns should execute automatically!")
        print()
        
        # Show updated campaigns
        updated_campaigns = await campaigns_col.find({
            "status": "scheduled",
            "scheduledFor": {"$gte": now}
        }).to_list(length=None)
        
        print(f"Scheduled campaigns now due to execute in the next 5 minutes:")
        for campaign in updated_campaigns:
            print(f"  - {campaign.get('campaignName')} (scheduled for {campaign.get('scheduledFor')})")
        
        print()
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        await close_mongo_connection()


async def check_scheduler_status():
    """Check current scheduler status"""
    
    try:
        await connect_to_mongo()
        campaigns_col = get_collection("campaigns")
        
        now = datetime.now(timezone.utc)
        
        print("\n" + "=" * 70)
        print("SCHEDULER STATUS CHECK")
        print("=" * 70)
        print(f"Current UTC time: {now.isoformat()}")
        print()
        
        # Count by status
        scheduled = await campaigns_col.count_documents({"status": "scheduled"})
        processing = await campaigns_col.count_documents({"status": "processing"})
        completed = await campaigns_col.count_documents({"status": "completed"})
        failed = await campaigns_col.count_documents({"status": "failed"})
        
        print(f"Campaigns by status:")
        print(f"  Scheduled:  {scheduled}")
        print(f"  Processing: {processing}")
        print(f"  Completed:  {completed}")
        print(f"  Failed:     {failed}")
        print()
        
        # Count due campaigns
        due = await campaigns_col.count_documents({
            "status": "scheduled",
            "scheduledFor": {"$lte": now}
        })
        print(f"Campaigns due to execute RIGHT NOW: {due}")
        print()
        
        # Show upcoming campaigns
        upcoming = await campaigns_col.find({
            "status": "scheduled",
            "scheduledFor": {"$gt": now}
        }).sort("scheduledFor", 1).limit(5).to_list(length=None)
        
        if upcoming:
            print("Next 5 campaigns scheduled to run:")
            for campaign in upcoming:
                time_until = campaign.get("scheduledFor") - now
                minutes_until = int(time_until.total_seconds() / 60)
                print(f"  - {campaign.get('campaignName')}")
                print(f"    Scheduled for: {campaign.get('scheduledFor')}")
                print(f"    In {minutes_until} minutes")
                print()
        else:
            print("No upcoming campaigns scheduled")
        
        print("=" * 70)
    
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    import sys
    
    print()
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "status":
            asyncio.run(check_scheduler_status())
        elif command == "fix":
            asyncio.run(fix_scheduled_campaigns())
        else:
            print(f"Unknown command: {command}")
            print("Usage:")
            print("  python fix_scheduled_campaigns.py status  # Check current status")
            print("  python fix_scheduled_campaigns.py fix     # Fix past campaigns")
    else:
        # Default: show status then ask to fix
        asyncio.run(check_scheduler_status())
        print()
        response = input("Run the fix to reschedule past campaigns? (yes/no): ")
        if response.lower() == "yes":
            asyncio.run(fix_scheduled_campaigns())
