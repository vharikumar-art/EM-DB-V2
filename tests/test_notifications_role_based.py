"""Test notification system with role-based logic (super_admin, admin, employee)"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, Mock
from app.notifications.service import (
    _get_all_super_admin_user_ids,
    _get_all_admin_user_ids,
    _is_employee_assigned_to_admin,
    create_notification
)
from app.notifications.router import _resolve_employee_id
from app.notifications.schema import NotificationType
from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException


class TestAdminCaching:
    """Test admin and super_admin caching functions"""
    
    @pytest.mark.asyncio
    async def test_super_admin_cache_fetches_all_super_admins(self):
        """Verify super_admin cache fetches from database"""
        mock_doc_1 = {"_id": "super_admin_1"}
        mock_doc_2 = {"_id": "super_admin_2"}
        
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = [mock_doc_1, mock_doc_2]
        
        mock_collection = AsyncMock()
        mock_collection.find.return_value = mock_cursor
        
        with patch('app.notifications.service.get_collection', return_value=mock_collection):
            result = await _get_all_super_admin_user_ids()
            
            assert len(result) == 2
            assert "super_admin_1" in result
            assert "super_admin_2" in result
            mock_collection.find.assert_called_once_with({"role": "super_admin"}, {"_id": 1})
    
    @pytest.mark.asyncio
    async def test_admin_cache_fetches_all_admins(self):
        """Verify admin cache fetches from database"""
        mock_doc_1 = {"_id": "admin_1"}
        mock_doc_2 = {"_id": "admin_2"}
        
        mock_cursor = AsyncMock()
        mock_cursor.__aiter__.return_value = [mock_doc_1, mock_doc_2]
        
        mock_collection = AsyncMock()
        mock_collection.find.return_value = mock_cursor
        
        with patch('app.notifications.service.get_collection', return_value=mock_collection):
            result = await _get_all_admin_user_ids()
            
            assert len(result) == 2
            assert "admin_1" in result
            assert "admin_2" in result
            mock_collection.find.assert_called_once_with({"role": "admin"}, {"_id": 1})
    
    @pytest.mark.asyncio
    async def test_cache_returns_cached_value_when_not_expired(self):
        """Verify cache returns stored value when TTL not expired"""
        from app.notifications.service import _super_admin_cache
        from datetime import timedelta
        
        # Mock a valid cache
        now = datetime.now(timezone.utc)
        _super_admin_cache["ids"] = ["cached_super_admin_1", "cached_super_admin_2"]
        _super_admin_cache["expires_at"] = now + timedelta(seconds=30)
        
        # Should not call database
        with patch('app.notifications.service.get_collection') as mock_get_col:
            result = await _get_all_super_admin_user_ids()
            
            assert result == ["cached_super_admin_1", "cached_super_admin_2"]
            mock_get_col.assert_not_called()  # Database NOT queried


class TestEmployeeAssignmentCheck:
    """Test _is_employee_assigned_to_admin function"""
    
    @pytest.mark.asyncio
    async def test_employee_assigned_to_admin_returns_true(self):
        """Verify assignment check returns True when employee IS assigned"""
        mock_employee = {
            "_id": "emp_123",
            "assignedToAdmin": "admin_456"
        }
        
        mock_cursor = AsyncMock()
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = mock_employee
        
        with patch('app.notifications.service.get_collection', return_value=mock_collection):
            result = await _is_employee_assigned_to_admin("emp_123", "admin_456")
            
            assert result is True
            mock_collection.find_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_employee_not_assigned_to_admin_returns_false(self):
        """Verify assignment check returns False when employee NOT assigned"""
        mock_employee = {
            "_id": "emp_123",
            "assignedToAdmin": "admin_999"  # Different admin
        }
        
        mock_collection = AsyncMock()
        mock_collection.find_one.return_value = mock_employee
        
        with patch('app.notifications.service.get_collection', return_value=mock_collection):
            result = await _is_employee_assigned_to_admin("emp_123", "admin_456")
            
            assert result is False
    
    @pytest.mark.asyncio
    async def test_admin_own_employee_record_match_returns_true(self):
        """Verify returns True when admin's own employee record is being checked"""
        # First call returns None (employee not assigned to anyone)
        # Second call returns admin's own employee record
        mock_admin_employee = {
            "_id": "emp_123",
            "userId": "admin_456"
        }
        
        mock_collection = AsyncMock()
        mock_collection.find_one.side_effect = [None, mock_admin_employee]
        
        with patch('app.notifications.service.get_collection', return_value=mock_collection):
            result = await _is_employee_assigned_to_admin("emp_123", "admin_456")
            
            assert result is True


class TestRoleBasedNotificationResolution:
    """Test _resolve_employee_id with different roles"""
    
    @pytest.mark.asyncio
    async def test_super_admin_can_view_any_employee(self):
        """Super admin should access any employee's notifications"""
        current_user = CurrentUser(user_id="super_admin_1", role="super_admin")
        
        result = await _resolve_employee_id(current_user, employee_id_query="emp_999")
        
        assert result == "emp_999"
    
    @pytest.mark.asyncio
    async def test_super_admin_defaults_to_own_user_id_if_no_query(self):
        """Super admin should get own user_id if no employeeId provided"""
        current_user = CurrentUser(user_id="super_admin_1", role="super_admin")
        
        result = await _resolve_employee_id(current_user, employee_id_query=None)
        
        assert result == "super_admin_1"
    
    @pytest.mark.asyncio
    async def test_admin_can_view_assigned_employee(self):
        """Admin should access assigned employee's notifications"""
        current_user = CurrentUser(user_id="admin_1", role="admin")
        
        with patch('app.notifications.service._is_employee_assigned_to_admin', return_value=True):
            result = await _resolve_employee_id(current_user, employee_id_query="emp_456")
            
            assert result == "emp_456"
    
    @pytest.mark.asyncio
    async def test_admin_cannot_view_unassigned_employee(self):
        """Admin should NOT access unassigned employee's notifications"""
        current_user = CurrentUser(user_id="admin_1", role="admin")
        
        with patch('app.notifications.service._is_employee_assigned_to_admin', return_value=False):
            with pytest.raises(ForbiddenException) as exc_info:
                await _resolve_employee_id(current_user, employee_id_query="emp_999")
            
            assert "You do not have access" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_admin_defaults_to_own_user_id_if_no_query(self):
        """Admin should default to own user_id if no employeeId provided"""
        current_user = CurrentUser(user_id="admin_1", role="admin")
        
        result = await _resolve_employee_id(current_user, employee_id_query=None)
        
        assert result == "admin_1"
    
    @pytest.mark.asyncio
    async def test_employee_always_gets_own_notifications(self):
        """Employee should always get own notifications"""
        current_user = CurrentUser(user_id="user_1", role="employee")
        
        mock_employee = {"id": "emp_789"}
        mock_collection = AsyncMock()
        
        with patch('app.notifications.service.get_employee_by_user_id', return_value=mock_employee):
            result = await _resolve_employee_id(current_user, employee_id_query=None)
            
            assert result == "emp_789"


class TestNotificationCreationFanOut:
    """Test notification creation with fan-out logic"""
    
    @pytest.mark.asyncio
    async def test_notification_fan_out_to_super_admins(self):
        """Verify notifications are fanned out to super_admins"""
        mock_notif_col = AsyncMock()
        mock_notif_col.insert_one.return_value = MagicMock(inserted_id="notif_id_1")
        mock_notif_col.find_one.return_value = {
            "_id": "notif_id_1",
            "employeeId": "emp_123",
            "message": "Test",
            "type": "info"
        }
        
        with patch('app.notifications.service.get_collection', return_value=mock_notif_col), \
             patch('app.notifications.service._get_all_super_admin_user_ids', return_value=["super_admin_1", "super_admin_2"]), \
             patch('app.notifications.service._get_all_admin_user_ids', return_value=[]), \
             patch('app.notifications.service.manager.send_personal_message', new_callable=AsyncMock), \
             patch('app.notifications.service.serialize_doc', return_value={"id": "notif_id_1"}):
            
            await create_notification("emp_123", "Test", NotificationType.INFO)
            
            # Should call send_personal_message for:
            # 1. Direct employee
            # 2. super_admin_1
            # 3. super_admin_2
            assert mock_notif_col.insert_one.call_count >= 3  # Employee + 2 super_admins
    
    @pytest.mark.asyncio
    async def test_notification_fan_out_respects_admin_assignment(self):
        """Verify admins only get notifications for assigned employees"""
        mock_notif_col = AsyncMock()
        mock_notif_col.insert_one.return_value = MagicMock(inserted_id="notif_id_1")
        mock_notif_col.find_one.return_value = {
            "_id": "notif_id_1",
            "employeeId": "emp_123",
            "message": "Test",
            "type": "info"
        }
        
        # Mock: super_admins = [], admins = [admin_1, admin_2]
        # admin_1 IS assigned to emp_123, admin_2 is NOT
        
        async def mock_is_assigned(emp_id, admin_id):
            return admin_id == "admin_1"  # Only admin_1 is assigned
        
        with patch('app.notifications.service.get_collection', return_value=mock_notif_col), \
             patch('app.notifications.service._get_all_super_admin_user_ids', return_value=[]), \
             patch('app.notifications.service._get_all_admin_user_ids', return_value=["admin_1", "admin_2"]), \
             patch('app.notifications.service._is_employee_assigned_to_admin', side_effect=mock_is_assigned), \
             patch('app.notifications.service.manager.send_personal_message', new_callable=AsyncMock), \
             patch('app.notifications.service.serialize_doc', return_value={"id": "notif_id_1"}):
            
            await create_notification("emp_123", "Test", NotificationType.INFO)
            
            # Should insert for: employee + admin_1 (only assigned)
            # Should NOT insert for: admin_2
            assert mock_notif_col.insert_one.call_count == 2


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
