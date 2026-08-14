from datetime import datetime, timezone

from app.database.mongodb import get_collection
from app.settings.model import build_setting_document
from app.settings.schema import SettingCreate, SettingUpdate
from app.utils.response import serialize_doc, serialize_list, to_object_id

COLLECTION = "settings"


def _normalize_values(values) -> list[str]:
    if isinstance(values, list):
        return [str(v).strip() for v in values if str(v).strip()]
    if isinstance(values, str) and values.strip():
        return [values.strip()]
    return []


async def create_setting(payload: dict | SettingCreate) -> dict:
    col = get_collection(COLLECTION)
    data = payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
    key = (data.get("key") or "branch").strip()
    if not key:
        raise ValueError("Setting key is required")

    values = _normalize_values(data.get("values"))
    if not values:
        raise ValueError("At least one setting value is required")

    doc = build_setting_document(key=key, values=values)
    result = await col.insert_one(doc)
    created = await col.find_one({"_id": result.inserted_id})
    return serialize_doc(created)


async def list_settings() -> list[dict]:
    col = get_collection(COLLECTION)
    docs = [d async for d in col.find({})]
    return serialize_list(docs)


async def list_setting_values(key: str) -> list[str]:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"key": key})
    if not doc:
        return []

    values = doc.get("values")
    if isinstance(values, list):
        return sorted({str(v).strip() for v in values if str(v).strip()})
    return []


async def list_branch_options() -> list[str]:
    return await list_setting_values("branch")


async def get_setting(setting_id: str) -> dict:
    col = get_collection(COLLECTION)
    doc = await col.find_one({"_id": to_object_id(setting_id)})
    if not doc:
        raise ValueError("Setting not found")
    return serialize_doc(doc)


async def update_setting(setting_id: str, payload: SettingUpdate) -> dict:
    col = get_collection(COLLECTION)
    existing = await col.find_one({"_id": to_object_id(setting_id)})
    if not existing:
        raise ValueError("Setting not found")

    update_data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not update_data:
        return serialize_doc(existing)

    if "values" in update_data:
        update_data["values"] = _normalize_values(update_data["values"])

    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = await col.find_one_and_update({"_id": to_object_id(setting_id)}, {"$set": update_data}, return_document=True)
    if not result:
        raise ValueError("Setting not found")
    return serialize_doc(result)


async def delete_setting(setting_id: str) -> None:
    col = get_collection(COLLECTION)
    await col.delete_one({"_id": to_object_id(setting_id)})
