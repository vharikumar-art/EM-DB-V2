"""Tests for role-based notification visibility and fan-out."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bson import ObjectId

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException
from app.notifications import service as notification_service
from app.notifications.router import _resolve_employee_id
from app.notifications.schema import NotificationType


class AsyncCursor:
    def __init__(self, documents):
        self.documents = iter(documents)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.documents)
        except StopIteration:
            raise StopAsyncIteration


class TestAdminCaching(unittest.IsolatedAsyncioTestCase):
    async def test_super_admin_cache_fetches_all_super_admins(self):
        notification_service._super_admin_cache = {"ids": [], "expires_at": None}
        users = MagicMock()
        users.find.return_value = AsyncCursor(
            [{"_id": "super_admin_1"}, {"_id": "super_admin_2"}]
        )

        with patch(
            "app.database.mongodb.get_collection", return_value=users
        ) as get_collection:
            result = await notification_service._get_all_super_admin_user_ids()

        self.assertEqual(result, ["super_admin_1", "super_admin_2"])
        get_collection.assert_called_once_with("users")
        users.find.assert_called_once_with({"role": "super_admin"}, {"_id": 1})

    async def test_admin_cache_fetches_all_admins(self):
        notification_service._admin_cache = {"ids": [], "expires_at": None}
        users = MagicMock()
        users.find.return_value = AsyncCursor(
            [{"_id": "admin_1"}, {"_id": "admin_2"}]
        )

        with patch(
            "app.database.mongodb.get_collection", return_value=users
        ) as get_collection:
            result = await notification_service._get_all_admin_user_ids()

        self.assertEqual(result, ["admin_1", "admin_2"])
        get_collection.assert_called_once_with("users")
        users.find.assert_called_once_with({"role": "admin"}, {"_id": 1})

    async def test_cache_returns_cached_value_when_not_expired(self):
        cached_ids = ["cached_super_admin_1", "cached_super_admin_2"]
        notification_service._super_admin_cache = {
            "ids": cached_ids,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=30),
        }

        with patch("app.database.mongodb.get_collection") as get_collection:
            result = await notification_service._get_all_super_admin_user_ids()

        self.assertEqual(result, cached_ids)
        get_collection.assert_not_called()


class TestEmployeeAssignmentCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        notification_service._super_admin_cache = {"ids": [], "expires_at": None}
        notification_service._admin_cache = {"ids": [], "expires_at": None}

    def _collections(self, access_level, employee_documents):
        admin_user_id = ObjectId()
        admin_employee_id = ObjectId()
        users = MagicMock()
        users.find_one = AsyncMock(return_value={"accessLevel": access_level})
        employees = MagicMock()
        employees.find_one = AsyncMock(
            side_effect=[
                {"_id": admin_employee_id},
                *employee_documents,
            ]
        )
        return admin_user_id, admin_employee_id, users, employees

    async def test_employee_assigned_to_partial_admin_returns_true(self):
        employee_id = ObjectId()
        admin_user_id, admin_employee_id, users, employees = self._collections(
            "partial",
            [{"_id": employee_id, "assignedToAdmin": None}],
        )
        employees.find_one.side_effect = [
            {"_id": admin_employee_id},
            {"_id": employee_id, "assignedToAdmin": str(admin_employee_id)},
        ]

        with patch.object(
            notification_service,
            "get_collection",
            side_effect=lambda name: {"users": users, "employees": employees}[name],
        ):
            result = await notification_service._is_employee_assigned_to_admin(
                str(employee_id), str(admin_user_id)
            )

        self.assertTrue(result)

    async def test_employee_assigned_to_another_admin_returns_false(self):
        employee_id = ObjectId()
        admin_user_id, _admin_employee_id, users, employees = self._collections(
            "partial",
            [{"_id": employee_id, "assignedToAdmin": str(ObjectId())}],
        )

        with patch.object(
            notification_service,
            "get_collection",
            side_effect=lambda name: {"users": users, "employees": employees}[name],
        ):
            result = await notification_service._is_employee_assigned_to_admin(
                str(employee_id), str(admin_user_id)
            )

        self.assertFalse(result)

    async def test_admin_own_employee_record_is_in_scope(self):
        admin_user_id = ObjectId()
        admin_employee_id = ObjectId()
        users = MagicMock()
        users.find_one = AsyncMock(return_value={"accessLevel": "partial"})
        employees = MagicMock()
        employees.find_one = AsyncMock(
            return_value={"_id": admin_employee_id, "userId": str(admin_user_id)}
        )

        with patch.object(
            notification_service,
            "get_collection",
            side_effect=lambda name: {"users": users, "employees": employees}[name],
        ):
            result = await notification_service._is_employee_assigned_to_admin(
                str(admin_employee_id), str(admin_user_id)
            )

        self.assertTrue(result)
        employees.find_one.assert_awaited_once_with({"userId": str(admin_user_id)})


class TestRoleBasedNotificationResolution(unittest.IsolatedAsyncioTestCase):
    async def test_super_admin_can_view_any_employee(self):
        current_user = CurrentUser(user_id="super_admin_1", role="super_admin")

        result = await _resolve_employee_id(current_user, employee_id_query="emp_999")

        self.assertEqual(result, "emp_999")

    async def test_super_admin_defaults_to_own_user_id_if_no_query(self):
        current_user = CurrentUser(user_id="super_admin_1", role="super_admin")

        result = await _resolve_employee_id(current_user, employee_id_query=None)

        self.assertEqual(result, "super_admin_1")

    async def test_admin_can_view_assigned_employee(self):
        current_user = CurrentUser(user_id="admin_1", role="admin")
        assignment_check = AsyncMock(return_value=True)

        with patch.object(
            notification_service,
            "_is_employee_assigned_to_admin",
            assignment_check,
        ):
            result = await _resolve_employee_id(
                current_user, employee_id_query="emp_456"
            )

        self.assertEqual(result, "emp_456")
        assignment_check.assert_awaited_once_with("emp_456", "admin_1")

    async def test_admin_cannot_view_unassigned_employee(self):
        current_user = CurrentUser(user_id="admin_1", role="admin")
        with patch.object(
            notification_service,
            "_is_employee_assigned_to_admin",
            new=AsyncMock(return_value=False),
        ):
            with self.assertRaisesRegex(
                ForbiddenException, "You do not have access"
            ):
                await _resolve_employee_id(
                    current_user, employee_id_query="emp_999"
                )

    async def test_admin_defaults_to_own_user_id_if_no_query(self):
        current_user = CurrentUser(user_id="admin_1", role="admin")

        result = await _resolve_employee_id(current_user, employee_id_query=None)

        self.assertEqual(result, "admin_1")

    async def test_employee_resolves_to_own_employee_record(self):
        current_user = CurrentUser(user_id="user_1", role="employee")
        employee = {"id": "emp_789"}

        with patch(
            "app.notifications.router.get_employee_by_user_id",
            new=AsyncMock(return_value=employee),
        ) as get_employee:
            result = await _resolve_employee_id(current_user, employee_id_query=None)

        self.assertEqual(result, "emp_789")
        get_employee.assert_awaited_once_with("user_1")


class TestNotificationCreationFanOut(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        notification_service._super_admin_cache = {"ids": [], "expires_at": None}
        notification_service._admin_cache = {"ids": [], "expires_at": None}

    def _notification_collection(self):
        collection = MagicMock()
        collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="notif_id_1")
        )
        collection.find_one = AsyncMock(
            return_value={
                "_id": "notif_id_1",
                "employeeId": "emp_123",
                "message": "Test",
                "type": "info",
            }
        )
        return collection

    async def test_notification_fans_out_to_super_admins(self):
        notifications = self._notification_collection()

        with (
            patch.object(
                notification_service, "get_collection", return_value=notifications
            ),
            patch.object(
                notification_service,
                "_get_all_super_admin_user_ids",
                new=AsyncMock(return_value=["super_admin_1", "super_admin_2"]),
            ),
            patch.object(
                notification_service,
                "_get_all_admin_user_ids",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                notification_service,
                "manager",
            ) as manager,
            patch.object(
                notification_service,
                "serialize_doc",
                return_value={"id": "notif_id_1"},
            ),
        ):
            manager.send_personal_message = AsyncMock()
            await notification_service.create_notification(
                "emp_123", "Test", NotificationType.INFO
            )

        self.assertEqual(notifications.insert_one.await_count, 3)
        self.assertEqual(manager.send_personal_message.await_count, 3)

    async def test_notification_fan_out_only_to_admins_in_scope(self):
        notifications = self._notification_collection()
        scope_check = AsyncMock(
            side_effect=lambda _employee_id, admin_id: admin_id == "admin_1"
        )

        with (
            patch.object(
                notification_service, "get_collection", return_value=notifications
            ),
            patch.object(
                notification_service,
                "_get_all_super_admin_user_ids",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(
                notification_service,
                "_get_all_admin_user_ids",
                new=AsyncMock(return_value=["admin_1", "admin_2"]),
            ),
            patch.object(
                notification_service,
                "_is_employee_in_admin_scope",
                scope_check,
            ),
            patch.object(
                notification_service,
                "manager",
            ) as manager,
            patch.object(
                notification_service,
                "serialize_doc",
                return_value={"id": "notif_id_1"},
            ),
        ):
            manager.send_personal_message = AsyncMock()
            await notification_service.create_notification(
                "emp_123", "Test", NotificationType.INFO
            )

        self.assertEqual(notifications.insert_one.await_count, 2)
        self.assertEqual(manager.send_personal_message.await_count, 2)
        self.assertEqual(scope_check.await_count, 2)


if __name__ == "__main__":
    unittest.main()
