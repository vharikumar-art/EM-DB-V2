from app.database.mongodb import get_collection
from app.logs.model import LogAction, build_log_document
from app.schemas.common import PaginationParams
from app.utils.pagination import build_paginated_response
from app.utils.response import serialize_doc, serialize_list

COLLECTION = "logs"


async def list_logs(
    employee_id: str | None,
    params: PaginationParams,
    action_filter: str | None = None,
) -> dict:
    logs = get_collection(COLLECTION)
    query: dict = {}
    if employee_id:
        query["employeeId"] = employee_id
    if action_filter:
        query["action"] = action_filter.upper()

    total = await logs.count_documents(query)
    cursor = logs.find(query).sort("createdAt", -1).skip(params.skip).limit(params.pageSize)
    docs = serialize_list([d async for d in cursor])
    return build_paginated_response(docs, total, params)


async def record_campaign_start(employee_id: str, profile_id: str) -> dict:
    logs = get_collection(COLLECTION)
    doc = build_log_document(
        employee_id=employee_id,
        profile_id=profile_id,
        action=LogAction.CAMPAIGN_STARTED,
    )
    result = await logs.insert_one(doc)
    created = await logs.find_one({"_id": result.inserted_id})
    return serialize_doc(created)
