import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from bson import ObjectId

from app.core.dependencies import CurrentUser, resolve_employee_context, resolve_write_employee_context
from app.core.exceptions import ForbiddenException
from app.users.schema import UserCreate, UserRole, AdminAccessLevel
from app.users.service import create_user
from app.email_master.service import update_email


def test_full_admin_cannot_create_another_admin():
    """Verify that full admin cannot create another admin."""
    async def _test():
        current_admin = CurrentUser(user_id="admin-1", role="admin", access_level="full")
        payload = UserCreate(
            name="New Admin",
            email="newadmin@example.com",
            password="Password123!",
            role=UserRole.ADMIN,
            branch="Chennai"
        )
        mock_users_col = MagicMock()
        mock_users_col.find_one = AsyncMock(return_value=None)
        with patch("app.users.service.get_collection", return_value=mock_users_col):
            try:
                await create_user(payload, current_user=current_admin)
                assert False, "Should have raised ForbiddenException"
            except ForbiddenException as e:
                assert "Only super admins can create admin users" in str(e)

    asyncio.run(_test())


def test_super_admin_can_create_admin():
    """Verify that super_admin can create admin."""
    async def _test():
        current_super_admin = CurrentUser(user_id="super-1", role="super_admin", access_level="full")
        payload = UserCreate(
            name="New Admin",
            email="newadmin@example.com",
            password="Password123!",
            role=UserRole.ADMIN,
            accessLevel=AdminAccessLevel.FULL,
            branch="Chennai"
        )
        new_id = ObjectId()
        user_in_db = {
            "_id": new_id,
            "name": "New Admin",
            "email": "newadmin@example.com",
            "role": "admin",
            "accessLevel": "full",
            "branch": "Chennai",
            "status": "active"
        }
        mock_users_col = MagicMock()
        # First find_one is checking existing email -> None, second find_one is returning created doc
        mock_users_col.find_one = AsyncMock(side_effect=[None, user_in_db])
        mock_users_col.insert_one = AsyncMock(return_value=MagicMock(inserted_id=new_id))
        
        mock_emp_col = MagicMock()
        mock_emp_col.insert_one = AsyncMock()

        with patch("app.users.service.get_collection") as mock_get_col:
            def side_effect(col_name):
                if col_name == "users":
                    return mock_users_col
                return mock_emp_col
            mock_get_col.side_effect = side_effect

            user_doc = await create_user(payload, current_user=current_super_admin)
            assert user_doc["role"] == "admin"
            assert user_doc["accessLevel"] == "full"

    asyncio.run(_test())


def test_resolve_employee_context_full_admin_branch_fallback():
    """Verify full admin gets all employee IDs in their branch even if branch is only on users doc."""
    async def _test():
        full_admin = CurrentUser(user_id=str(ObjectId()), role="admin", access_level="full")

        # Mock admin's employee doc without branch
        mock_admin_emp = {"id": "emp-admin-1", "userId": full_admin.user_id, "branch": None}
        
        # Mock users collection returning branch="Bangalore"
        mock_users_col = MagicMock()
        mock_users_col.find_one = AsyncMock(return_value={"_id": ObjectId(full_admin.user_id), "branch": "Bangalore"})

        # Mock employees collection finding subordinates in "Bangalore"
        subordinate_docs = [
            {"_id": ObjectId("60c72b2f9b1d8b2bad000001"), "userId": "u1", "branch": "Bangalore"},
            {"_id": ObjectId("60c72b2f9b1d8b2bad000002"), "userId": "u2", "branch": "Bangalore"},
        ]
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=subordinate_docs)
        mock_emp_col = MagicMock()
        mock_emp_col.find = MagicMock(return_value=mock_cursor)

        with patch("app.employees.service.get_employee_by_user_id", new=AsyncMock(return_value=mock_admin_emp)), \
             patch("app.database.mongodb.get_collection") as mock_get_col:
            def side_effect(col_name):
                if col_name == "users":
                    return mock_users_col
                return mock_emp_col
            mock_get_col.side_effect = side_effect

            scope, is_admin = await resolve_employee_context(full_admin)
            assert is_admin is True
            assert set(scope) == {"emp-admin-1", "60c72b2f9b1d8b2bad000001", "60c72b2f9b1d8b2bad000002"}

    asyncio.run(_test())


def test_partial_admin_write_restriction():
    """Verify partial admin cannot write to another employee's scope."""
    async def _test():
        partial_admin = CurrentUser(user_id="partial-u1", role="admin", access_level="partial")

        with patch("app.employees.service.get_employee_by_user_id", new=AsyncMock(return_value={"id": "emp-partial-1"})):
            # Attempting to write on behalf of another employee
            try:
                await resolve_write_employee_context(partial_admin, employee_id_param="emp-other-2")
                assert False, "Should have raised ForbiddenException"
            except ForbiddenException as e:
                assert "Partial-access admins cannot modify assigned employee data" in str(e)

            # Writing to their own employee ID succeeds
            scope, is_admin = await resolve_write_employee_context(partial_admin, employee_id_param="emp-partial-1")
            assert scope == "emp-partial-1"
            assert is_admin is False

    asyncio.run(_test())


def test_update_email_replicates_to_profile_emails():
    """Verify that updating email_master replicates allowed fields to profile_emails."""
    async def _test():
        email_id = str(ObjectId())
        update_data = {
            "fullName": "Jane Doe Updated",
            "designation": "Lead Scientist",
            "domain": "Biotech",
            "email": "hack@example.com" # Should be removed by update_email
        }

        mock_master_col = MagicMock()
        now_doc = {
            "_id": ObjectId(email_id),
            "fullName": "Jane Doe Updated",
            "designation": "Lead Scientist",
            "domain": "Biotech",
            "email": "original@example.com",
        }
        mock_master_col.find_one_and_update = AsyncMock(return_value=now_doc)

        mock_pe_col = MagicMock()
        mock_pe_col.update_many = AsyncMock()

        with patch("app.email_master.service.get_collection") as mock_get_col, \
             patch("app.email_master.service.invalidate_dropdown_cache"):
            def side_effect(col_name):
                if col_name == "profile_emails":
                    return mock_pe_col
                return mock_master_col
            mock_get_col.side_effect = side_effect

            result = await update_email(email_id, update_data)
            assert result["fullName"] == "Jane Doe Updated"

            # Check replicate call
            mock_pe_col.update_many.assert_called_once()
            filter_arg, update_arg = mock_pe_col.update_many.call_args[0]
            assert filter_arg == {"masterEmailId": email_id}
            assert update_arg["$set"]["fullName"] == "Jane Doe Updated"
            assert update_arg["$set"]["designation"] == "Lead Scientist"
            assert update_arg["$set"]["domain"] == "Biotech"
            assert "email" not in update_arg["$set"]

    asyncio.run(_test())
