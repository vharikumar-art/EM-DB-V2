from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.campaigns import service
from app.campaigns.model import CampaignStatus
from app.campaigns.schema import CampaignStartRequest
from app.core.dependencies import CurrentUser, get_current_user
from app.employees.service import get_employee_by_user_id
from app.schemas.common import ApiResponse, PaginationParams
from app.utils.pagination import pagination_params

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


async def _resolve_employee(current_user: CurrentUser) -> tuple[str, bool]:
    is_admin = current_user.role == "admin"
    if is_admin:
        return "", True
    employee = await get_employee_by_user_id(current_user.user_id)
    return employee["id"], False


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

@router.post("/start", response_model=ApiResponse)
async def start_campaign(
    payload: CampaignStartRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Create a campaign record, then kick off the async send loop as a
    background task.  Returns immediately with the campaign document.
    """
    employee_id, is_admin = await _resolve_employee(current_user)

    campaign = await service.create_campaign(payload, employee_id, is_admin)

    # Import here to avoid circular imports at module load time
    from app.campaign_engine.worker import run_campaign

    background_tasks.add_task(run_campaign, campaign["id"])

    return ApiResponse(
        message="Campaign started",
        data=campaign,
    )


# ---------------------------------------------------------------------------
# Status controls
# ---------------------------------------------------------------------------

@router.post("/{campaign_id}/pause", response_model=ApiResponse)
async def pause_campaign(
    campaign_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    campaign = await service.set_status(
        campaign_id, CampaignStatus.PAUSED, employee_id, is_admin
    )
    return ApiResponse(message="Campaign paused", data=campaign)


@router.post("/{campaign_id}/resume", response_model=ApiResponse)
async def resume_campaign(
    campaign_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    campaign = await service.set_status(
        campaign_id, CampaignStatus.RUNNING, employee_id, is_admin
    )

    from app.campaign_engine.worker import run_campaign

    background_tasks.add_task(run_campaign, campaign["id"])
    return ApiResponse(message="Campaign resumed", data=campaign)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get("", response_model=ApiResponse)
async def list_campaigns(
    employeeId: str | None = Query(default=None),
    status: str | None = Query(default=None),
    profileId: str | None = Query(default=None),
    params: PaginationParams = Depends(pagination_params),
    current_user: CurrentUser = Depends(get_current_user),
):
    if current_user.role == "admin":
        target_id = employeeId  # None = all employees
    else:
        employee = await get_employee_by_user_id(current_user.user_id)
        target_id = employee["id"]

    result = await service.list_campaigns(
        employee_id=target_id,
        params=params,
        status_filter=status,
        profile_id=profileId,
    )
    return ApiResponse(message="Campaigns fetched", data=result)


@router.get("/{campaign_id}", response_model=ApiResponse)
async def get_campaign(
    campaign_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    employee_id, is_admin = await _resolve_employee(current_user)
    campaign = await service.get_campaign(campaign_id, employee_id, is_admin)
    return ApiResponse(message="Campaign fetched", data=campaign)
