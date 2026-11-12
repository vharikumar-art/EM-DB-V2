from unittest.mock import AsyncMock

import pytest
from bson import ObjectId

from app.core.dependencies import CurrentUser
from app.employees import service


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents

    async def find_one(self, query, *_args, **_kwargs):
        return next(
            (
                document
                for document in self.documents
                if all(document.get(key) == value for key, value in query.items())
            ),
            None,
        )

    async def delete_one(self, query):
        original_count = len(self.documents)
        self.documents[:] = [
            document
            for document in self.documents
            if document.get("_id") != query.get("_id")
        ]
        return type(
            "DeleteResult",
            (),
            {"deleted_count": original_count - len(self.documents)},
        )()

    async def update_many(self, _query, _update):
        return None


@pytest.mark.anyio
async def test_delete_employee_preserves_data_and_removes_account(monkeypatch):
    user_id = ObjectId()
    employee_id = ObjectId()
    employee_doc = {
        "id": str(employee_id),
        "userId": str(user_id),
        "name": "Chennai User",
        "branch": "Chennai",
        "assignedToAdmin": "admin-employee-id",
    }
    user_doc = {
        "_id": user_id,
        "name": "Chennai User",
        "email": "chennai@example.test",
        "branch": "Chennai",
    }
    employees = FakeCollection([{"_id": employee_id}])
    users = FakeCollection([user_doc])
    preserve = AsyncMock()
    monkeypatch.setattr(service, "get_employee", AsyncMock(return_value=employee_doc))
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: {"employees": employees, "users": users}[name],
    )
    monkeypatch.setattr(
        "app.users.unknown.preserve_deleted_user_data",
        preserve,
    )

    await service.delete_employee(
        str(employee_id),
        CurrentUser(str(ObjectId()), "super_admin"),
    )

    preserve.assert_awaited_once_with(
        user_id=str(user_id),
        employee_id=str(employee_id),
        deleted_name="Chennai User",
        branch="Chennai",
        assigned_to_admin="admin-employee-id",
    )
    assert users.documents == []
    assert employees.documents == []
