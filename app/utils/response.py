from typing import Any

from bson import ObjectId


def serialize_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Convert a MongoDB document into a JSON-safe dict with `id` instead of `_id`."""
    if doc is None:
        return None
    from datetime import datetime
    result = dict(doc)
    _id = result.pop("_id", None)
    if _id is not None:
        result["id"] = str(_id)
    for key, value in result.items():
        if isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            # Always serialize as UTC ISO string with Z suffix so the frontend
            # correctly interprets the timestamp as UTC (not local time).
            result[key] = value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return result


def serialize_list(docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [serialize_doc(d) for d in docs]


def to_object_id(id_str: str) -> ObjectId:
    from app.core.exceptions import BadRequestException

    if not ObjectId.is_valid(id_str):
        raise BadRequestException(f"Invalid id format: {id_str}")
    return ObjectId(id_str)
