from fastapi import APIRouter, Depends

from app.auth import service
from app.auth.schema import LoginRequest, LogoutRequest, RefreshRequest, TokenPair
from app.core.dependencies import CurrentUser, get_current_user
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=ApiResponse[TokenPair])
async def login(payload: LoginRequest):
    tokens = await service.login(payload)
    return ApiResponse(message="Login successful", data=tokens)


@router.post("/refresh", response_model=ApiResponse[TokenPair])
async def refresh(payload: RefreshRequest):
    tokens = await service.refresh_access_token(payload.refreshToken)
    return ApiResponse(message="Token refreshed", data=tokens)


@router.post("/logout", response_model=ApiResponse)
async def logout(payload: LogoutRequest, current_user: CurrentUser = Depends(get_current_user)):
    await service.logout(payload.refreshToken, current_user.user_id)
    return ApiResponse(message="Logged out successfully")
