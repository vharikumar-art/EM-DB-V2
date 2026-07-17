from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.campaigns import service
from app.campaigns.model import CampaignStatus
from app.campaigns.schema import CampaignStartRequest, CampaignScheduleRequest, SchedulerProcessResponse, SchedulerStatusResponse
from app.campaigns.scheduler import process_scheduled_campaigns, get_scheduler_status
from app.core.dependencies import CurrentUser, get_current_user, resolve_employee_context, require_admin
from app.core.exceptions import BadRequestException
from app.schemas.common import ApiResponse, PaginationParams
from app.utils.pagination import pagination_params
from app.campaigns.cleanup import get_duplicate_campaigns, consolidate_campaigns

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

@router.post("/start", response_model=ApiResponse)
async def start_campaign(
    payload: CampaignStartRequest,
    background_tasks: BackgroundTasks,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Create a campaign record and kick off async send loop."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    campaign = await service.create_campaign(payload, employee_id, is_admin)

    from app.campaign_engine.worker import run_campaign
    background_tasks.add_task(run_campaign, campaign["id"])

    return ApiResponse(message="Campaign started", data=campaign)


@router.post("/{campaign_id}/pause", response_model=ApiResponse)
async def pause_campaign(
    campaign_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    campaign = await service.set_status(
        campaign_id, CampaignStatus.PAUSED, employee_id, is_admin
    )
    return ApiResponse(message="Campaign paused", data=campaign)


@router.post("/{campaign_id}/resume", response_model=ApiResponse)
async def resume_campaign(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    campaign = await service.set_status(
        campaign_id, CampaignStatus.RUNNING, employee_id, is_admin
    )

    from app.campaign_engine.worker import run_campaign
    background_tasks.add_task(run_campaign, campaign["id"])
    return ApiResponse(message="Campaign resumed", data=campaign)

@router.get("", response_model=ApiResponse)
async def list_campaigns(
    employeeId: str | None = Query(default=None),
    status: str | None = Query(default=None),
    profileId: str | None = Query(default=None),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    """List campaigns. Admins can specify employeeId to view any employee's campaigns."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)

    result = await service.list_campaigns(
        employee_id=employee_id if employee_id else None,
        params=params,
        status_filter=status,
        profile_id=profileId,
    )
    return ApiResponse(message="Campaigns fetched", data=result)


@router.get("/{campaign_id}", response_model=ApiResponse)
async def get_campaign(
    campaign_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get campaign details. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    campaign = await service.get_campaign(campaign_id, employee_id, is_admin)
    return ApiResponse(message="Campaign fetched", data=campaign)


@router.delete("/{campaign_id}", response_model=ApiResponse)
async def delete_campaign(
    campaign_id: str,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Delete campaign. Can't delete running campaigns. Admins can specify employeeId."""
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    await service.delete_campaign(campaign_id, employee_id, is_admin)
    return ApiResponse(message="Campaign deleted")


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

@router.post("/schedule", response_model=ApiResponse)
async def schedule_campaign(
    payload: CampaignScheduleRequest,
    employeeId: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Create a campaign scheduled for future execution.
    
    The campaign will not execute immediately. It will be queued and executed
    by the Linux Cron scheduler when the scheduled_for time arrives.
    """
    employee_id, is_admin = await resolve_employee_context(current_user, employeeId)
    campaign = await service.create_scheduled_campaign(payload, employee_id, is_admin)
    return ApiResponse(message="Campaign scheduled successfully", data=campaign)


# @router.post("/process-scheduled", response_model=ApiResponse)
# async def process_scheduled_campaigns_endpoint(
#     current_user: CurrentUser = Depends(get_current_user),
# ):
@router.post("/process-scheduled",response_model=ApiResponse)
async def process_scheduled_campaigns_endpoint():
    """
    Process all campaigns due for execution.
    
    Called by Linux Cron every minute. This endpoint:
    1. Finds all campaigns where status='scheduled' and scheduledFor <= now
    2. Atomically transitions each to 'processing' status
    3. Executes each campaign using existing run_campaign() logic
    4. Updates status to 'completed' or 'scheduled' (for retry)
    
    Returns execution summary with counts and errors.
    
    NOTE: This endpoint must be called by an automated process (Linux Cron).
    Manual calls are allowed for testing/debugging.
    """
    # Only admins should call this endpoint in production
    # For now, allow any authenticated user for testing
    from datetime import datetime, timezone
    print(f"[SCHEDULER DEBUG] Current server time: {datetime.now(timezone.utc).isoformat()}")
    
    result = await process_scheduled_campaigns()
    return ApiResponse(
        message="Scheduled campaigns processed",
        data=result
    )


@router.get("/scheduler/status", response_model=ApiResponse)
async def get_scheduler_status_endpoint(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Get current scheduler health and status.
    
    Returns:
    - campaigns_awaiting_execution: Due campaigns not yet executed
    - campaigns_currently_processing: Campaigns being processed
    - campaigns_completed_24h: Completed campaigns (last 24 hours)
    - campaigns_failed_24h: Failed campaigns (last 24 hours)
    - health: Scheduler health status
    """
    status = await get_scheduler_status()
    return ApiResponse(message="Scheduler status", data=status)


# ---------------------------------------------------------------------------
# Admin maintenance (duplicate detection/consolidation)
# ---------------------------------------------------------------------------

@router.get("/admin/duplicates/{profile_id}", response_model=ApiResponse)
async def detect_duplicates(
    profile_id: str,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    ADMIN ONLY: Detect duplicate campaigns for a profile.
    
    Returns list of all campaigns for a profile so admin can identify
    if there are multiple campaigns with same profile (duplicates).
    """
    duplicates = await get_duplicate_campaigns(profile_id)
    return ApiResponse(
        message="Duplicate campaigns detected",
        data={"profileId": profile_id, "campaigns": duplicates}
    )


@router.post("/admin/consolidate", response_model=ApiResponse)
async def consolidate_duplicates(
    profileId: str = Query(...),
    keepCampaignId: str = Query(...),
    current_user: CurrentUser = Depends(require_admin),
):
    """
    ADMIN ONLY: Consolidate duplicate campaigns into one.
    
    - Merges counters (sent, failed, skipped) from all campaigns
    - Repoints all profile_emails to kept campaign
    - Deletes other campaigns
    
    Args:
        profileId: The profile ID
        keepCampaignId: Which campaign to keep (usually most recent)
    """
    result = await consolidate_campaigns(profileId, keepCampaignId)
    return ApiResponse(message="Campaigns consolidated", data=result)
