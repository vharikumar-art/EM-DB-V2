from unittest.mock import patch, AsyncMock

import pytest

from app.campaign_engine.worker import _run
from app.campaigns.model import CampaignStatus

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
@pytest.mark.parametrize(
    "smtp_error",
    [
        "SMTP error: (550, b'5.4.5 Daily user sending limit exceeded')",
        "SMTP error: (451, b'Temporary SMTP failure')",
    ],
)
async def test_smtp_errors_fail_campaign(mock_collections, smtp_error):
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
            mock_pe.get_sent_domain_counts_today = AsyncMock(return_value={})
            # Return 1 pending email
            mock_pe.get_pending_batch = AsyncMock(side_effect=[
                [{"id": "pe1", "email": "lead@test.com", "masterEmailId": "m1"}], 
                [] # empty on second call to break loop
            ])
            mock_pe.mark_sending = AsyncMock(return_value=True)
            mock_pe.mark_pending = AsyncMock()
            mock_pe.mark_failed = AsyncMock()
            
            # Mock send_email to return an SMTP-side error
            with patch("app.campaign_engine.worker.send_email", new_callable=AsyncMock) as mock_send:
                class SendResult:
                    success = False
                    error = smtp_error
                mock_send.return_value = SendResult()
                
                with patch("app.campaign_engine.worker.campaign_service") as mock_camp:
                    mock_camp.claim_campaign_worker = AsyncMock(return_value=True)
                    mock_camp.release_campaign_worker = AsyncMock()
                    mock_camp.is_worker_active = AsyncMock(return_value=True)
                    mock_camp.start_campaign_worker = AsyncMock(return_value=True)
                    mock_camp.increment_counters = AsyncMock()
                    mock_camp.finalize_campaign = AsyncMock()
                    mock_camp.abort_campaign = AsyncMock()

                    with patch("app.campaign_engine.worker._push_progress", new_callable=AsyncMock) as push_progress:
                        await _run("507f1f77bcf86cd799439011")

                    mock_pe.mark_pending.assert_not_called()
                    mock_pe.mark_failed.assert_awaited_once_with("pe1", smtp_error)
                    mock_camp.increment_counters.assert_awaited_once_with(
                        "507f1f77bcf86cd799439011", failed=1
                    )
                    mock_camp.abort_campaign.assert_awaited_once()
                    failure_message = mock_camp.abort_campaign.await_args.args[1]
                    assert "test@gmail.com" in failure_message
                    assert smtp_error in failure_message
                    mock_send.assert_awaited_once()
                    push_progress.assert_awaited_once()
                    mock_camp.start_campaign_worker.assert_awaited_once_with(
                        "507f1f77bcf86cd799439011"
                    )


@pytest.mark.anyio
async def test_immediate_campaign_daily_limit_pauses_campaign(mock_collections):
    mock_campaigns, mock_profiles, _ = mock_collections
    campaign_id = "507f1f77bcf86cd799439011"
    mock_campaigns.find_one.return_value = {
        "_id": campaign_id,
        "profileId": "507f1f77bcf86cd799439012",
        "employeeId": "emp1",
        "status": CampaignStatus.RUNNING.value,
        "dailyLimit": 50,
        "executionSent": 50,
        "recurrenceType": "once",
        "campaignName": "Test Campaign",
    }
    mock_profiles.find_one.return_value = {
        "_id": "507f1f77bcf86cd799439012",
        "employeeId": "emp1",
        "gmailAccount": "test@gmail.com",
        "templates": [{"id": "t1", "subject": "Hello", "body": "World"}],
        "sendingOptions": {"delayMin": 0, "delayMax": 0},
    }

    with (
        patch(
            "app.campaign_engine.worker.get_credentials_for_send",
            new_callable=AsyncMock,
            return_value={
                "_id": "cred1",
                "email": "test@gmail.com",
                "password": "pass",
                "smtpHost": "smtp.gmail.com",
                "smtpPort": 587,
                "useTls": True,
            },
        ),
        patch("app.campaign_engine.worker.pe_service") as mock_pe,
        patch("app.campaign_engine.worker.send_email", new_callable=AsyncMock) as mock_send,
        patch("app.campaign_engine.worker.campaign_service") as mock_camp,
    ):
        mock_pe.get_sent_domain_counts_today = AsyncMock(return_value={})
        mock_pe.get_pending_batch = AsyncMock(
            return_value=[{"id": "pe1", "email": "lead@test.com"}]
        )
        mock_camp.claim_campaign_worker = AsyncMock(return_value=True)
        mock_camp.release_campaign_worker = AsyncMock()
        mock_camp.is_worker_active = AsyncMock(return_value=True)
        mock_camp.start_campaign_worker = AsyncMock(return_value=True)
        mock_camp.pause_campaign_worker = AsyncMock()
        mock_camp.abort_campaign = AsyncMock()

        await _run(campaign_id)

    mock_camp.pause_campaign_worker.assert_awaited_once_with(campaign_id)
    mock_camp.abort_campaign.assert_not_awaited()
    mock_send.assert_not_awaited()
