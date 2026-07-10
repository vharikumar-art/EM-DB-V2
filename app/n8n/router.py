from fastapi import APIRouter, Depends

from app.core.dependencies import verify_n8n_api_key
from app.emails.service import get_emails_for_profile
from app.n8n import service
from app.n8n.schema import StartCampaignRequest
from app.profiles.service import get_profile
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/n8n", tags=["n8n Integration"], dependencies=[Depends(verify_n8n_api_key)])


@router.post("/start-campaign", response_model=ApiResponse)
async def start_campaign(payload: StartCampaignRequest):
    result = await service.start_campaign(payload.profileId)
    return ApiResponse(message="Webhook accepted", data=result)


@router.get("/profiles/{profile_id}", response_model=ApiResponse)
async def get_profile_settings(profile_id: str):
    """n8n reads profile settings (Gmail account, sending options) before a run."""
    profile = await get_profile(profile_id, employee_id="", is_admin=True)
    return ApiResponse(message="Profile settings fetched", data=profile)


@router.get("/profiles/{profile_id}/emails", response_model=ApiResponse)
async def get_profile_emails(profile_id: str):
    """n8n reads the matching lead list for a profile's stored filters."""
    emails = await get_emails_for_profile(profile_id, employee_id="", is_admin=True)
    return ApiResponse(message="Matching emails fetched", data=emails)
