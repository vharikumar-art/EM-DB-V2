import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.database.mongodb import get_collection
from app.logs.service import record_campaign_start
from app.utils.response import serialize_doc, to_object_id


async def start_campaign(profile_id: str) -> dict:
    profiles = get_collection("profiles")
    profile = await profiles.find_one({"_id": to_object_id(profile_id)})
    if not profile:
        raise BadRequestException("Profile not found")
    if not profile.get("isActive", False):
        raise BadRequestException("Profile is not active. Activate it before starting a campaign.")

    profile = serialize_doc(profile)

    await record_campaign_start(profile["employeeId"], profile_id)

    webhook_payload = {
        "profileId": profile_id,
        "employeeId": profile["employeeId"],
        "gmailAccount": profile["gmailAccount"],
        "options": profile["options"],
    }

    webhook_accepted = True
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.N8N_WEBHOOK_URL,
                json=webhook_payload,
                headers={"X-API-KEY": settings.N8N_API_KEY},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        # We still return "started" from our side (the log is recorded); the caller
        # can inspect the webhookAccepted flag to know if n8n actually picked it up.
        webhook_accepted = False

    return {
        "status": "started",
        "profileId": profile_id,
        "webhookAccepted": webhook_accepted,
    }
