import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
from app.campaign_engine.worker import _run
from app.campaigns.model import CampaignStatus
from datetime import datetime, timezone

# We will mock the database collections and services
@pytest.fixture
def mock_collections():
    with patch("app.campaign_engine.worker.get_collection") as mock_get_col:
        mock_campaigns = AsyncMock()
        mock_profiles = AsyncMock()
        mock_profile_emails = AsyncMock()
        
        def side_effect(name):
            if name == "campaigns": return mock_campaigns
            if name == "profiles": return mock_profiles
            if name == "profile_emails": return mock_profile_emails
            return AsyncMock()
            
        mock_get_col.side_effect = side_effect
        yield mock_campaigns, mock_profiles, mock_profile_emails

@pytest.mark.anyio
async def test_smtp_daily_limit_handling(mock_collections):
    mock_campaigns, mock_profiles, mock_profile_emails = mock_collections
    
    # Mock campaign document
    mock_campaigns.find_one.return_value = {
        "_id": "507f1f77bcf86cd799439011",
        "profileId": "507f1f77bcf86cd799439012",
        "employeeId": "emp1",
        "status": CampaignStatus.PROCESSING.value,
        "dailyLimit": 100,
        "recurrenceType": "once",
        "campaignName": "Test Campaign"
    }
    
    # Mock profile document
    mock_profiles.find_one.return_value = {
        "_id": "507f1f77bcf86cd799439012",
        "employeeId": "emp1",
        "gmailAccount": "test@gmail.com",
        "templates": [{"id": "t1", "subject": "Hello", "body": "World"}],
        "sendingOptions": {"delayMin": 0, "delayMax": 0}
    }
    
    # Mock credentials
    with patch("app.campaign_engine.worker.get_credentials_for_send", new_callable=AsyncMock) as mock_creds:
        mock_creds.return_value = {
            "_id": "cred1",
            "email": "test@gmail.com",
            "password": "pass",
            "smtpHost": "smtp.gmail.com",
            "smtpPort": 587,
            "useTls": True
        }
        
        # Mock pe_service
        with patch("app.campaign_engine.worker.pe_service") as mock_pe:
            # Return 1 pending email
            mock_pe.get_pending_batch = AsyncMock(side_effect=[
                [{"id": "pe1", "email": "lead@test.com", "masterEmailId": "m1"}], 
                [] # empty on second call to break loop
            ])
            mock_pe.mark_sending = AsyncMock(return_value=True)
            mock_pe.mark_pending = AsyncMock()
            mock_pe.mark_failed = AsyncMock()
            
            # Mock send_email to fail with daily limit error
            with patch("app.campaign_engine.worker.send_email", new_callable=AsyncMock) as mock_send:
                class SendResult:
                    success = False
                    error = "450 4.2.1 Daily user sending quota exceeded"
                mock_send.return_value = SendResult()
                
                with patch("app.campaign_engine.worker.campaign_service") as mock_camp:
                    mock_camp.claim_campaign_worker = AsyncMock(return_value=True)
                    mock_camp.release_campaign_worker = AsyncMock()
                    mock_camp.is_paused = AsyncMock(return_value=False)
                    mock_camp.set_status = AsyncMock()
                    mock_camp.increment_counters = AsyncMock()
                    mock_camp.finalize_campaign = AsyncMock()
                    
                    with patch("app.campaign_engine.worker.create_notification") as mock_notif:
                        
                        # Run worker logic directly
                        await _run("507f1f77bcf86cd799439011")
                        
                        # Assertions
                        # 1. Should call mark_pending since it's a daily limit error
                        mock_pe.mark_pending.assert_called_once_with("pe1")
                        
                        # 2. Should NOT call mark_failed
                        mock_pe.mark_failed.assert_not_called()
                        
                        # 3. Should pause the campaign because recurrenceType = once
                        mock_camp.set_status.assert_any_call("507f1f77bcf86cd799439011", CampaignStatus.PAUSED, "emp1", is_admin=True)
                        
                        # 4. Should send a warning notification
                        mock_notif.assert_called_once()
                        args, kwargs = mock_notif.call_args
                        assert "reached SMTP daily limit" in kwargs["message"]

if __name__ == "__main__":
    asyncio.run(test_smtp_daily_limit_handling())
