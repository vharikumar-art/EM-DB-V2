from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import FileResponse

from app.core.dependencies import CurrentUser, get_current_user, require_admin, require_full_admin, require_write_access
from app.schemas.common import ApiResponse
from app.users import service
from app.users.schema import (
    PasswordReset,
    PasswordUpdate,
    UserCreate,
    UserProfileOut,
    UserUpdate,
)

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=ApiResponse[UserProfileOut])
async def get_my_profile(current_user: CurrentUser = Depends(get_current_user)):
    profile = await service.get_my_profile(current_user.user_id)
    return ApiResponse(message="Profile fetched", data=profile)


@router.put("/me/profile-picture", response_model=ApiResponse)
async def upload_my_profile_picture(
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
):
    contents = await file.read(service.PROFILE_PICTURE_MAX_BYTES + 1)
    await service.save_profile_picture(current_user.user_id, contents)
    return ApiResponse(
        message="Profile picture updated",
        data={"profilePictureUrl": "/users/me/profile-picture"},
    )


@router.delete("/me/profile-picture", response_model=ApiResponse)
async def remove_my_profile_picture(
    current_user: CurrentUser = Depends(get_current_user),
):
    await service.remove_profile_picture(current_user.user_id)
    return ApiResponse(message="Profile picture removed")


@router.get("/me/profile-picture")
async def get_my_profile_picture(current_user: CurrentUser = Depends(get_current_user)):
    path, media_type = service.get_profile_picture(current_user.user_id)
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{user_id}/profile-picture", dependencies=[Depends(get_current_user)])
async def get_user_profile_picture(user_id: str):
    path, media_type = await service.get_user_profile_picture(user_id)
    return FileResponse(
        path,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/initial-super-admin", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_initial_super_admin(payload: UserCreate):
    user = await service.create_initial_super_admin(payload)
    return ApiResponse(message="Initial super admin created", data=user)


@router.post("/initial-admin", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def create_initial_admin(payload: UserCreate):
    user = await service.create_initial_admin(payload)
    return ApiResponse(message="Initial admin created", data=user)


@router.post("", response_model=ApiResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_full_admin)])
async def create_user(payload: UserCreate, current_user: CurrentUser = Depends(get_current_user)):
    """Create a new user (admin or employee based on role field)"""
    user = await service.create_user(payload, current_user)
    return ApiResponse(message="User created successfully", data=user)


# ── must be before /{user_id} routes so FastAPI doesn't treat "migrate-branch" as a user_id
@router.post("/migrate-branch", response_model=ApiResponse, dependencies=[Depends(require_full_admin)])
async def migrate_branch():
    """Add branch 'Vellore' to all existing users that don't have it"""
    result = await service.migrate_add_branch()
    return ApiResponse(message="Migration completed", data=result)


from app.core.dependencies import CurrentUser, get_current_user

@router.get("", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def list_all_users(current_user: CurrentUser = Depends(get_current_user)):
    users = await service.list_users(current_user)
    return ApiResponse(message="Users fetched", data=users)


@router.get("/{user_id}/details", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def get_user_details(
    user_id: str,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Get full user profile with performance stats (uploads, profiles, campaigns)."""
    data = await service.get_user_details(user_id, current_user)
    return ApiResponse(message="User details fetched", data=data)


@router.get("/{user_id}", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def get_user(user_id: str):
    user = await service.get_user_by_id(user_id)
    return ApiResponse(message="User fetched", data=user)


@router.patch("/{user_id}", response_model=ApiResponse, dependencies=[Depends(require_write_access)])
async def update_user(user_id: str, payload: UserUpdate, current_user: CurrentUser = Depends(get_current_user)):
    user = await service.update_user(user_id, payload, current_user)
    return ApiResponse(message="User updated", data=user)


@router.patch("/{user_id}/password", response_model=ApiResponse, dependencies=[Depends(require_admin)])
async def update_user_password(
    user_id: str,
    payload: PasswordUpdate,
    current_user: CurrentUser = Depends(get_current_user),
):
    user = await service.update_password(user_id, payload, current_user)
    return ApiResponse(message="Password updated", data=user)


@router.post(
    "/{user_id}/password-reset",
    response_model=ApiResponse,
    dependencies=[Depends(require_full_admin)],
)
async def reset_user_password(
    user_id: str,
    payload: PasswordReset,
    current_user: CurrentUser = Depends(get_current_user),
):
    user = await service.reset_user_password(
        user_id,
        payload.new_password,
        current_user,
    )
    return ApiResponse(message="Password reset", data=user)


@router.delete("/{user_id}", response_model=ApiResponse)
async def delete_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_full_admin),
):
    await service.delete_user(user_id, actor_role=current_user.role, actor_id=current_user.user_id)
    return ApiResponse(message="User deleted")
