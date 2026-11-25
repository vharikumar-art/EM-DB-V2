from datetime import date
import re

from fastapi import APIRouter, Depends, Query

from app.achievements import service
from app.achievements.schema import AchievementMetric, AchievementScope
from app.core.dependencies import CurrentUser, get_current_user
from app.core.exceptions import BadRequestException, ForbiddenException
from app.dashboard.service import _resolve_dashboard_scope
from app.database.mongodb import get_collection
from app.schemas.common import ApiResponse
from app.utils.response import to_object_id

router = APIRouter(prefix="/achievements", tags=["Achievements"])


@router.get("/leaderboard", response_model=ApiResponse)
async def get_achievements_leaderboard(
    metric: AchievementMetric | None = Query(
        default=None,
        description="Leaderboard metric: mail uploads, converted replies, or both",
    ),
    scope: AchievementScope | None = Query(
        default=None,
        description="Global leaderboard for super admins or branch leaderboard",
    ),
    branch: str | None = Query(default=None, description="Required for a super-admin branch leaderboard"),
    startDate: date | None = Query(default=None, description="Inclusive start date for the live leaderboard (YYYY-MM-DD)"),
    endDate: date | None = Query(default=None, description="Inclusive end date for the live leaderboard (YYYY-MM-DD)"),
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get the live leaderboard; employees receive fixed branch-only results."""
    is_employee = current_user.role == "employee"
    if current_user.role not in {"employee", "admin", "super_admin"}:
        raise ForbiddenException("You do not have access to the leaderboard")
    if is_employee and any(
        value is not None
        for value in (metric, scope, branch, startDate, endDate)
    ):
        raise BadRequestException("Employees cannot apply leaderboard filters")
    if (startDate is None) != (endDate is None):
        raise BadRequestException("startDate and endDate must be provided together")
    if startDate and endDate and startDate > endDate:
        raise BadRequestException("startDate must be on or before endDate")

    selected_metric = metric or ("both" if is_employee else "mail")
    selected_scope = "branch" if is_employee else scope or (
        "global" if current_user.role == "super_admin" else "branch"
    )
    permitted_user_ids: set[str] | None = None

    if current_user.role == "super_admin":
        if selected_scope == "branch" and not (branch and branch.strip()):
            raise BadRequestException("branch is required for a branch leaderboard")
        if selected_scope == "global" and branch:
            raise BadRequestException("branch cannot be supplied for a global leaderboard")
    else:
        if selected_scope != "branch":
            raise ForbiddenException("Admins can only view their branch leaderboard")
        employees = get_collection("employees")
        employee = await employees.find_one(
            {"userId": current_user.user_id},
            {"branch": 1},
        )
        user = await get_collection("users").find_one(
            {"_id": to_object_id(current_user.user_id)},
            {"branch": 1},
        )
        admin_branch = (user or {}).get("branch") or (employee or {}).get("branch")
        if not admin_branch:
            raise BadRequestException("Your account is not associated with a branch")
        if branch and branch.strip().casefold() != str(admin_branch).strip().casefold():
            raise ForbiddenException("You can only view your own branch leaderboard")
        branch = admin_branch

        if current_user.role == "admin" and current_user.access_level == "partial":
            dashboard_scope = await _resolve_dashboard_scope(
                current_user.role,
                current_user.user_id,
            )
            permitted_user_ids = set(dashboard_scope["scope_user_ids"])
            super_admin_branch = {
                str(super_admin["_id"])
                async for super_admin in get_collection("users").find(
                    {
                        "role": "super_admin",
                        "branch": {
                            "$regex": f"^{re.escape(str(admin_branch).strip())}$",
                            "$options": "i",
                        },
                    },
                    {"_id": 1},
                )
            }
            permitted_user_ids.update(super_admin_branch)

    result = await service.get_leaderboard(
        metric=selected_metric,
        scope=selected_scope,
        branch=branch.strip() if branch else None,
        permitted_user_ids=permitted_user_ids,
        start_date=startDate,
        end_date=endDate,
    )
    if is_employee:
        result = {
            "scope": result["scope"],
            "branch": result["branch"],
            "metric": result["metric"],
            "livePeriod": result["livePeriod"],
            "liveLeaderboard": result["liveLeaderboard"],
            "currentPeriod": result["currentPeriod"],
            "currentTop3": result["currentTop3"],
        }
    return ApiResponse(message="Achievement leaderboard fetched", data=result)
