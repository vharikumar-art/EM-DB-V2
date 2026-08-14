import asyncio
from unittest.mock import AsyncMock, patch

from app.settings.service import create_setting, list_branch_options, update_setting


class FakeBranchCursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, field, direction):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.docs:
            raise StopAsyncIteration
        return self.docs.pop(0)


def test_create_setting_and_list_branch_options():
    mock_collection = AsyncMock()
    mock_collection.insert_one.return_value = type("Result", (), {"inserted_id": "setting_1"})()
    mock_collection.find_one.return_value = {"_id": "507f1f77bcf86cd799439011", "key": "branch", "values": ["Vellore"]}
    mock_collection.find_one_and_update.return_value = {
        "_id": "507f1f77bcf86cd799439011",
        "key": "branch",
        "values": ["Vellore", "Chennai"],
    }
    mock_collection.find = lambda query: FakeBranchCursor([
        {"_id": "507f1f77bcf86cd799439011", "key": "branch", "values": ["Vellore"]},
    ])

    async def run_checks():
        with patch("app.settings.service.get_collection", return_value=mock_collection):
            created = await create_setting({"key": "branch", "values": ["Vellore"]})
            branches = await list_branch_options()
            updated = await update_setting("507f1f77bcf86cd799439011", type("Payload", (), {"model_dump": lambda self, exclude_unset=True: {"values": ["Vellore", "Chennai"]}})())
        assert created["key"] == "branch"
        assert branches == ["Vellore"]
        assert updated["values"] == ["Vellore", "Chennai"]

    asyncio.run(run_checks())
