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
from app.employees.service import get_employee_by_user_id


async def login(payload: LoginRequest) -> TokenPair:
    user = await get_user_by_email(str(payload.email))
    if not user or not verify_password(payload.password, user["password"]):
        raise UnauthorizedException("Invalid email or password")

    if user.get("status") != "active":
        raise UnauthorizedException("This account is inactive. Contact an administrator.")

    user_id = str(user["_id"])
    role = user["role"]
    
    # Get employeeId if user is employee (not admin)
    employee_id = None
    if role == "employee":
        try:
            employee = await get_employee_by_user_id(user_id)
            employee_id = employee["id"]
        except:
            pass  # If employee record not found, continue without it
    
    return TokenPair(
        accessToken=create_access_token(user_id, role, employee_id),
        refreshToken=create_refresh_token(user_id, role, employee_id),
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
    employee_id = payload.get("employee_id")  # Extract employee_id from token

    return TokenPair(
        accessToken=create_access_token(user_id, role, employee_id),
        refreshToken=create_refresh_token(user_id, role, employee_id),
    )


async def logout(refresh_token: str, user_id: str) -> None:
    revoked = get_collection(REVOKED_TOKENS_COLLECTION)
    await revoked.insert_one(build_revoked_token_document(refresh_token, user_id))
