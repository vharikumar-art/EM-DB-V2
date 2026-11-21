from dataclasses import dataclass

from bson import ObjectId

from app.core.exceptions import UnauthorizedException
from app.database.mongodb import get_collection


@dataclass(frozen=True)
class UserAuthState:
    role: str
    access_level: str


async def load_active_user_auth_state(user_id: str) -> UserAuthState:
    if not ObjectId.is_valid(user_id):
        raise UnauthorizedException("Malformed token subject")

    user = await get_collection("users").find_one(
        {"_id": ObjectId(user_id)},
        {"role": 1, "accessLevel": 1, "status": 1},
    )
    if not user or user.get("status") != "active":
        raise UnauthorizedException("User account is inactive or no longer exists")

    role = user.get("role")
    if not role:
        raise UnauthorizedException("User account has no assigned role")

    return UserAuthState(
        role=role,
        access_level=user.get("accessLevel", "full"),
    )
