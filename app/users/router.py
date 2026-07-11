from fastapi import APIRouter, Depends, status

from app.core.dependencies import require_admin
from app.schemas.common import ApiResponse
from app.users import service
from app.users.schema import UserCreate, UserUpdate, PasswordUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/initial-admin", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_initial_admin(payload: UserCreate):
    user = await service.create_initial_admin(payload)
    return ApiResponse(message="Initial admin created", data=user)


# ── must be before /{user_id} routes so FastAPI doesn't treat "migrate-branch" as a user_id
@router.post("/migrate-branch", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def migrate_branch():
    """Add branch 'Vellore' to all existing users that don't have it"""
    result = await service.migrate_add_branch()
    return ApiResponse(message="Migration completed", data=result)


@router.get("", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def list_all_users():
    users = await service.list_users()
    return ApiResponse(message="Users fetched", data=users)


@router.get("/{user_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def get_user(user_id: str):
    user = await service.get_user_by_id(user_id)
    return ApiResponse(message="User fetched", data=user)


@router.patch("/{user_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def update_user(user_id: str, payload: UserUpdate):
    user = await service.update_user(user_id, payload)
    return ApiResponse(message="User updated", data=user)


@router.patch("/{user_id}/password", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def update_user_password(user_id: str, payload: PasswordUpdate):
    user = await service.update_password(user_id, payload)
    return ApiResponse(message="Password updated", data=user)


@router.delete("/{user_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def delete_user(user_id: str):
    await service.delete_user(user_id)
    return ApiResponse(message="User deleted")
