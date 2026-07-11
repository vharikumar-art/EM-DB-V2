"""
Campaign cleanup utilities for fixing duplicate/orphaned campaign issues.
Used to consolidate multiple campaign documents for the same profile into one.
"""

from datetime import datetime, timezone
from app.database.mongodb import get_collection
from app.campaigns.model import CampaignStatus
from app.profiles.service import get_profile

COLLECTION = "campaigns"


async def get_duplicate_campaigns(profile_id: str) -> list[dict]:
    """
    Find all campaigns for a profile with different statuses (potential duplicates).
    
    Returns list of campaigns grouped by profile, showing which ones are duplicates.
    """
    campaigns = get_collection(COLLECTION)
    
    # Find all campaigns for this profile, sorted by creation date
    docs = await campaigns.find(
        {"profileId": profile_id}
    ).sort("createdAt", -1).to_list(None)
    
    return [
        {
            "id": doc.get("_id"),
            "campaignName": doc.get("campaignName"),
            "status": doc.get("status"),
            "createdAt": doc.get("createdAt"),
            "totalEmails": doc.get("totalEmails"),
            "sent": doc.get("sent", 0),
        }
        for doc in docs
    ]


async def consolidate_campaigns(profile_id: str, keep_campaign_id: str) -> dict:
    """
    Consolidate multiple campaigns into one.
    
    - Keep the specified campaign (usually the most recent RUNNING one)
    - Merge counters from other campaigns into it
    - Delete other campaigns
    - Retag profile_emails to point to the kept campaign
    
    Args:
        profile_id: The profile these campaigns belong to
        keep_campaign_id: The campaign ID to keep
        
    Returns:
        Summary of what was consolidated
    """
    from bson import ObjectId
    
    campaigns = get_collection(COLLECTION)
    profile_emails = get_collection("profile_emails")
    
    # Get the campaign to keep
    keep_doc = await campaigns.find_one({"_id": ObjectId(keep_campaign_id)})
    if not keep_doc:
        raise ValueError(f"Campaign {keep_campaign_id} not found")
    
    # Get all other campaigns for this profile
    other_docs = await campaigns.find(
        {"profileId": profile_id, "_id": {"$ne": ObjectId(keep_campaign_id)}}
    ).to_list(None)
    
    if not other_docs:
        return {"message": "No duplicate campaigns found", "consolidated": 0}
    
    # Aggregate counters from other campaigns
    total_sent = keep_doc.get("sent", 0)
    total_failed = keep_doc.get("failed", 0)
    total_skipped = keep_doc.get("skipped", 0)
    
    for doc in other_docs:
        total_sent += doc.get("sent", 0)
        total_failed += doc.get("failed", 0)
        total_skipped += doc.get("skipped", 0)
    
    # Update the kept campaign with aggregated counters
    await campaigns.update_one(
        {"_id": ObjectId(keep_campaign_id)},
        {
            "$set": {
                "sent": total_sent,
                "failed": total_failed,
                "skipped": total_skipped,
                "consolidatedAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc),
            }
        }
    )
    
    # Retag all profile_emails to point to kept campaign
    other_ids = [doc["_id"] for doc in other_docs]
    await profile_emails.update_many(
        {"campaignId": {"$in": [str(cid) for cid in other_ids]}},
        {
            "$set": {
                "campaignId": keep_campaign_id,
                "updatedAt": datetime.now(timezone.utc),
            }
        }
    )
    
    # Delete other campaigns
    await campaigns.delete_many(
        {"_id": {"$in": other_ids}}
    )
    
    return {
        "message": "Campaigns consolidated successfully",
        "consolidated": len(other_docs),
        "kept_campaign_id": keep_campaign_id,
        "aggregated_counters": {
            "sent": total_sent,
            "failed": total_failed,
            "skipped": total_skipped,
        }
    }
