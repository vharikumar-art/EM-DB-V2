import smtplib
from datetime import datetime, timezone

from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException
from app.core.security import decrypt_password, encrypt_password
from app.database.mongodb import get_collection
from app.email_accounts.model import AccountType, build_email_account_document
from app.email_accounts.schema import EmailAccountCreate, EmailAccountUpdate
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "email_accounts"


async def create_account(employee_id: str, payload: EmailAccountCreate) -> dict:
    col = get_collection(COLLECTION)

    existing = await col.find_one({"employeeId": employee_id, "email": str(payload.email)})
    if existing:
        raise ConflictException(
            f"An account for {payload.email} already exists for this employee"
        )

    encrypted = encrypt_password(payload.appPassword)
    doc = build_email_account_document(
        employee_id=employee_id,
        email=str(payload.email),
        account_type=payload.accountType,
        display_name=payload.displayName or str(payload.email),
        encrypted_password=encrypted,
        smtp_host=payload.smtpHost,
        smtp_port=payload.smtpPort,
        use_tls=payload.useTls,
    )
    result = await col.insert_one(doc)
    created = await col.find_one({"_id": result.inserted_id})
    return _safe_serialize(created)


async def list_accounts(employee_id: str | None, is_admin: bool) -> list[dict]:
    col = get_collection(COLLECTION)
    query: dict = {} if is_admin and employee_id is None else {"employeeId": employee_id}
    cursor = col.find(query).sort("createdAt", -1)
    return [_safe_serialize(d) async for d in cursor]


async def get_account(account_id: str, employee_id: str, is_admin: bool) -> dict:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(account_id)})
    if not doc:
        raise NotFoundException("Email account not found")
    _assert_access(doc, employee_id, is_admin)
    return _safe_serialize(doc)


async def update_account(
    account_id: str, employee_id: str, is_admin: bool, payload: EmailAccountUpdate
) -> dict:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(account_id)})
    if not doc:
        raise NotFoundException("Email account not found")
    _assert_access(doc, employee_id, is_admin)

    update_data: dict = {}
    raw = payload.model_dump(exclude_unset=True)

    if "appPassword" in raw and raw["appPassword"]:
        update_data["encryptedPassword"] = encrypt_password(raw.pop("appPassword"))
    else:
        raw.pop("appPassword", None)

    for k, v in raw.items():
        if v is not None:
            update_data[k] = v

    if not update_data:
        return _safe_serialize(doc)

    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = await col.find_one_and_update(
        {"_id": to_object_id(account_id)},
        {"$set": update_data},
        return_document=True,
    )
    return _safe_serialize(result)


async def delete_account(account_id: str, employee_id: str, is_admin: bool) -> None:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(account_id)})
    if not doc:
        raise NotFoundException("Email account not found")
    _assert_access(doc, employee_id, is_admin)
    await col.delete_one({"_id": to_object_id(account_id)})


async def test_connection(account_id: str, employee_id: str, is_admin: bool) -> dict:
    """
    Attempt a live SMTP login to verify credentials.
    Returns success/failure without sending any email.
    """
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(account_id)})
    if not doc:
        raise NotFoundException("Email account not found")
    _assert_access(doc, employee_id, is_admin)

    try:
        plain_password = decrypt_password(doc["encryptedPassword"])
        _smtp_login_check(
            host=doc["smtpHost"],
            port=doc["smtpPort"],
            email=doc["email"],
            password=plain_password,
            use_tls=doc["useTls"],
        )
        await col.update_one(
            {"_id": doc["_id"]},
            {"$set": {"lastError": None, "lastErrorAt": None, "updatedAt": datetime.now(timezone.utc)}},
        )
        return {"success": True, "message": "Connection successful"}
    except Exception as exc:
        now = datetime.now(timezone.utc)
        await col.update_one(
            {"_id": doc["_id"]},
            {"$set": {"lastError": str(exc)[:300], "lastErrorAt": now, "updatedAt": now}},
        )
        return {"success": False, "message": str(exc)[:300]}


def _smtp_login_check(host: str, port: int, email: str, password: str, use_tls: bool) -> None:
    if use_tls:
        server = smtplib.SMTP(host, port, timeout=10)
        server.ehlo()
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(host, port, timeout=10)
    try:
        server.login(email, password)
    finally:
        server.quit()


# ---------------------------------------------------------------------------
# Internal — used by campaign engine
# ---------------------------------------------------------------------------

async def get_credentials_for_send(gmail_account: str) -> dict:
    """
    Retrieve and decrypt credentials for the given gmail_account email address.
    Called by the campaign engine immediately before each send batch.
    Returns: { email, password (plain), smtpHost, smtpPort, useTls }
    Raises BadRequestException if not found or inactive.
    """
    col = get_collection(COLLECTION)
    doc = await col.find_one({"email": gmail_account, "isActive": True})
    if not doc:
        raise BadRequestException(
            f"No active email account found for '{gmail_account}'. "
            "Add and activate it in Settings → Email Accounts before running a campaign."
        )
    plain_password = decrypt_password(doc["encryptedPassword"])
    return {
        "email": doc["email"],
        "password": plain_password,
        "displayName": doc.get("displayName", doc["email"]),
        "smtpHost": doc["smtpHost"],
        "smtpPort": doc["smtpPort"],
        "useTls": doc["useTls"],
        "_id": str(doc["_id"]),
    }


async def record_send(account_id: str) -> None:
    """Increment send counter and update lastUsedAt — called after each successful send."""
    col = get_collection(COLLECTION)
    now = datetime.now(timezone.utc)
    await col.update_one(
        {"_id": to_object_id(account_id)},
        {"$inc": {"sendCount": 1}, "$set": {"lastUsedAt": now, "updatedAt": now}},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _assert_access(doc: dict, employee_id: str, is_admin: bool) -> None:
    if not is_admin and doc.get("employeeId") != employee_id:
        raise ForbiddenException("Access denied")


def _safe_serialize(doc: dict) -> dict:
    """Serialize a MongoDB doc, stripping the encrypted password field."""
    from app.utils.response import serialize_doc
    result = serialize_doc(doc)
    result.pop("encryptedPassword", None)
    return result
