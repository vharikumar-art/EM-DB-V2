import asyncio

import pytest
from bson import ObjectId

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException
from app.schemas.common import PaginationParams
from app.emails import router as emails_router
from app.reports import router as reports_router


class AsyncCursor:
    def sort(self, *_args):
        return self

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class RecordingCollection:
    def __init__(self, document=None):
        self.document = document
        self.query = None

    def find(self, query):
        self.query = query
        return AsyncCursor()

    async def find_one(self, *_args):
        return self.document


@pytest.mark.parametrize(
    ("endpoint", "collection_name"),
    [
        (reports_router.export_email_master_csv, "email_master"),
        (reports_router.export_campaigns_csv, "campaigns"),
    ],
)
def test_admin_exports_without_employee_id_are_limited_to_resolved_scope(
    monkeypatch, endpoint, collection_name
):
    collection = RecordingCollection()

    async def resolve_scope(_user, _employee_id):
        return ["admin-employee", "assigned-employee"], True

    monkeypatch.setattr(reports_router, "resolve_employee_context", resolve_scope)
    monkeypatch.setattr(
        reports_router,
        "get_collection",
        lambda name: collection if name == collection_name else None,
    )

    asyncio.run(
        endpoint(
            employeeId=None,
            current_user=CurrentUser("admin-user", "admin", "partial"),
        )
    )

    assert collection.query == {
        "employeeId": {"$in": ["admin-employee", "assigned-employee"]}
    }


def test_profile_export_checks_admin_scope_before_exporting(monkeypatch):
    profile_id = str(ObjectId())
    profiles = RecordingCollection({"employeeId": "other-employee"})
    profile_emails = RecordingCollection()

    async def resolve_scope(_user, employee_id):
        assert employee_id == "other-employee"
        raise ForbiddenException("You do not have access to this employee's data")

    monkeypatch.setattr(reports_router, "resolve_employee_context", resolve_scope)
    monkeypatch.setattr(
        reports_router,
        "get_collection",
        lambda name: profiles if name == "profiles" else profile_emails,
    )

    with pytest.raises(ForbiddenException):
        asyncio.run(
            reports_router.export_profile_emails_csv(
                profileId=profile_id,
                sendStatus=None,
                current_user=CurrentUser("admin-user", "admin", "partial"),
            )
        )

    assert profile_emails.query is None


def test_email_list_uses_resolved_admin_scope(monkeypatch):
    captured = {}

    async def resolve_scope(_user, employee_id):
        assert employee_id is None
        return ["admin-employee", "assigned-employee"], True

    async def list_emails(employee_id, *_args, **_kwargs):
        captured["employee_id"] = employee_id
        return {}

    monkeypatch.setattr(emails_router, "resolve_employee_context", resolve_scope)
    monkeypatch.setattr(emails_router.service, "list_emails", list_emails)

    asyncio.run(
        emails_router.list_emails(
            employeeId=None,
            country=None,
            domain=None,
            includeDuplicates=True,
            params=PaginationParams(),
            current_user=CurrentUser("admin-user", "admin", "partial"),
        )
    )

    assert captured["employee_id"] == ["admin-employee", "assigned-employee"]
