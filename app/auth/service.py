from app.auth.model import REVOKED_TOKENS_COLLECTION, build_revoked_token_document
from app.auth.schema import LoginRequest, TokenPair
from app.core.exceptions import UnauthorizedException
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.database.mongodb import get_collection
from app.users.service import get_user_by_email


async def login(payload: LoginRequest) -> TokenPair:
    user = await get_user_by_email(str(payload.email))
    if not user or not verify_password(payload.password, user["password"]):
        raise UnauthorizedException("Invalid email or password")

    if user.get("status") != "active":
        raise UnauthorizedException("This account is inactive. Contact an administrator.")

    user_id = str(user["_id"])
    role = user["role"]
    return TokenPair(
        accessToken=create_access_token(user_id, role),
        refreshToken=create_refresh_token(user_id, role),
    )


async def refresh_access_token(refresh_token: str) -> TokenPair:
    revoked = get_collection(REVOKED_TOKENS_COLLECTION)
    if await revoked.find_one({"token": refresh_token}):
        raise UnauthorizedException("Refresh token has been revoked")

    try:
        payload = decode_token(refresh_token)
    except ValueError as exc:
        raise UnauthorizedException(str(exc)) from exc

    if payload.get("type") != "refresh":
        raise UnauthorizedException("Provide a refresh token")

    user_id = payload["sub"]
    role = payload["role"]

    return TokenPair(
        accessToken=create_access_token(user_id, role),
        refreshToken=create_refresh_token(user_id, role),
    )


async def logout(refresh_token: str, user_id: str) -> None:
    revoked = get_collection(REVOKED_TOKENS_COLLECTION)
    await revoked.insert_one(build_revoked_token_document(refresh_token, user_id))
