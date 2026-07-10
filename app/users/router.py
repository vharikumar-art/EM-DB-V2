from fastapi import APIRouter, Depends, status

from app.core.dependencies import require_admin
from app.schemas.common import ApiResponse
from app.users import service
from app.users.schema import UserCreate, UserUpdate

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/initial-admin", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_initial_admin(payload: UserCreate):
    user = await service.create_initial_admin(payload)
    return ApiResponse(message="Initial admin created", data=user)


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


@router.delete("/{user_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def delete_user(user_id: str):
    await service.delete_user(user_id)
    return ApiResponse(message="User deleted")
