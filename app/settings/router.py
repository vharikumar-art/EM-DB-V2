from fastapi import APIRouter, Depends, status

from app.core.dependencies import CurrentUser, get_current_user, require_admin
from app.schemas.common import ApiResponse
from app.settings.schema import SettingCreate, SettingUpdate
from app.settings.service import (
    create_setting,
    delete_setting,
    get_setting,
    list_branch_options,
    list_setting_values,
    list_settings,
    update_setting,
)

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)])
async def create_settings(payload: SettingCreate, current_user: CurrentUser = Depends(get_current_user)):
    setting = await create_setting(payload)
    return ApiResponse(message="Setting created", data=setting)


@router.get("", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def list_settings_route(current_user: CurrentUser = Depends(get_current_user)):
    settings = await list_settings()
    return ApiResponse(message="Settings fetched", data=settings)


@router.get("/options/{key}", response_model=ApiResponse)
async def get_setting_options(key: str, current_user: CurrentUser = Depends(get_current_user)):
    values = await list_setting_values(key)
    return ApiResponse(message=f"{key} options fetched", data=values)


@router.get("/branches", response_model=ApiResponse)
async def get_branch_dropdown(current_user: CurrentUser = Depends(get_current_user)):
    branches = await list_branch_options()
    return ApiResponse(message="Branches fetched", data=branches)


@router.get("/{setting_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def get_setting_route(setting_id: str, current_user: CurrentUser = Depends(get_current_user)):
    setting = await get_setting(setting_id)
    return ApiResponse(message="Setting fetched", data=setting)


@router.patch("/{setting_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def update_settings_route(setting_id: str, payload: SettingUpdate, current_user: CurrentUser = Depends(get_current_user)):
    setting = await update_setting(setting_id, payload)
    return ApiResponse(message="Setting updated", data=setting)


@router.delete("/{setting_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def delete_settings_route(setting_id: str, current_user: CurrentUser = Depends(get_current_user)):
    await delete_setting(setting_id)
    return ApiResponse(message="Setting deleted")
