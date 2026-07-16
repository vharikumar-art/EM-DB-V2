"""
Migration script to add scheduling fields to existing campaigns in MongoDB.

This script adds the following fields to all existing campaigns:
- scheduledFor: null (campaigns are not scheduled, they run immediately)
- processingStartedAt: null
- executionDuration: null
- errorMessage: null
- retryCount: 0
- maxRetries: 3

Run this script once after deploying the scheduler feature:
    python migrate_add_scheduling_fields.py
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.database.mongodb import connect_to_mongo, close_mongo_connection, get_database


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def migrate_campaigns() -> None:
    """Add scheduling fields to all existing campaigns."""
    try:
        await connect_to_mongo()
        db = get_database()
        campaigns_col = db["campaigns"]
        
        logger.info("Starting migration: adding scheduling fields to campaigns")
        
        # Count existing campaigns
        total_campaigns = await campaigns_col.count_documents({})
        logger.info(f"Found {total_campaigns} campaigns to update")
        
        if total_campaigns == 0:
            logger.info("No campaigns to migrate")
            return
        
        # Update all campaigns
        result = await campaigns_col.update_many(
            {},  # Match all documents
            {
                "$set": {
                    "scheduledFor": None,
                    "processingStartedAt": None,
                    "executionDuration": None,
                    "errorMessage": None,
                    "retryCount": 0,
                    "maxRetries": 3,
                    "updatedAt": datetime.now(timezone.utc),
                }
            }
        )
        
        logger.info(
            f"Migration completed successfully!\n"
            f"  - Matched documents: {result.matched_count}\n"
            f"  - Modified documents: {result.modified_count}"
        )
        
        # Verify the migration
        campaigns_with_scheduled_for = await campaigns_col.count_documents({
            "scheduledFor": {"$exists": True}
        })
        
        logger.info(
            f"Verification: {campaigns_with_scheduled_for}/{total_campaigns} "
            f"campaigns now have scheduling fields"
        )
        
        if campaigns_with_scheduled_for == total_campaigns:
            logger.info("✅ Migration verified successfully!")
        else:
            logger.warning(
                f"⚠️  Migration incomplete: {total_campaigns - campaigns_with_scheduled_for} "
                f"campaigns missing scheduling fields"
            )
    
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}", exc_info=True)
        raise
    
    finally:
        await close_mongo_connection()


async def rollback_migration() -> None:
    """
    Rollback migration by removing scheduling fields from campaigns.
    
    Only use if migration caused issues and you need to revert.
    """
    try:
        await connect_to_mongo()
        db = get_database()
        campaigns_col = db["campaigns"]
        
        logger.info("Starting rollback: removing scheduling fields from campaigns")
        
        # Remove scheduling fields
        result = await campaigns_col.update_many(
            {},
            {
                "$unset": {
                    "scheduledFor": "",
                    "processingStartedAt": "",
                    "executionDuration": "",
                    "errorMessage": "",
                    "retryCount": "",
                    "maxRetries": "",
                },
                "$set": {
                    "updatedAt": datetime.now(timezone.utc)
                }
            }
        )
        
        logger.info(
            f"Rollback completed!\n"
            f"  - Matched documents: {result.matched_count}\n"
            f"  - Modified documents: {result.modified_count}"
        )
    
    except Exception as e:
        logger.error(f"Rollback failed: {str(e)}", exc_info=True)
        raise
    
    finally:
        await close_mongo_connection()


async def check_migration_status() -> None:
    """Check if scheduling fields exist in campaigns."""
    try:
        await connect_to_mongo()
        db = get_database()
        campaigns_col = db["campaigns"]
        
        total = await campaigns_col.count_documents({})
        with_fields = await campaigns_col.count_documents({
            "scheduledFor": {"$exists": True}
        })
        
        logger.info(
            f"Migration Status:\n"
            f"  - Total campaigns: {total}\n"
            f"  - With scheduling fields: {with_fields}\n"
            f"  - Missing fields: {total - with_fields}\n"
            f"  - Status: {'✅ Complete' if with_fields == total else '⚠️  Incomplete'}"
        )
    
    except Exception as e:
        logger.error(f"Status check failed: {str(e)}", exc_info=True)
    
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "status":
            asyncio.run(check_migration_status())
        elif command == "rollback":
            confirm = input("⚠️  This will remove scheduling fields. Continue? (yes/no): ")
            if confirm.lower() == "yes":
                asyncio.run(rollback_migration())
            else:
                logger.info("Rollback cancelled")
        else:
            logger.error(f"Unknown command: {command}")
            print("Usage: python migrate_add_scheduling_fields.py [migrate|status|rollback]")
    else:
        # Default: run migration
        asyncio.run(migrate_campaigns())
