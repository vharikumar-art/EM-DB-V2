import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bson import ObjectId

from app.campaign_engine import worker


def test_worker_keeps_recurring_campaign_scheduled_until_pending_is_zero(monkeypatch):
    campaign_id = str(ObjectId())
    profile_id = str(ObjectId())
    employee_id = str(ObjectId())

    campaign_doc = {
        "_id": ObjectId(campaign_id),
        "campaignName": "Daily campaign",
        "profileId": profile_id,
        "employeeId": employee_id,
        "dailyLimit": 100,
        "recurrenceType": "daily",
        "status": "running",
        "totalEmails": 600,
        "sent": 100,
        "failed": 0,
        "skipped": 0,
        "pending": 500,
    }

    profile_doc = {
        "_id": ObjectId(profile_id),
        "profileName": "Demo profile",
        "employeeId": employee_id,
        "gmailAccount": "demo@gmail.com",
        "sendingOptions": {"delayMin": 1, "delayMax": 1},
        "templates": [{"name": "Default", "subject": "Hi {{first_name}}", "body": "Hello {{first_name}}"}],
    }

    lead = {"id": str(ObjectId()), "email": "lead@example.com", "first_name": "Ada"}

    class FakeCampaignsCollection:
        async def find_one(self, query, *args, **kwargs):
            return campaign_doc if query.get("_id") == ObjectId(campaign_id) else None

    class FakeProfilesCollection:
        async def find_one(self, query, *args, **kwargs):
            return profile_doc if query.get("_id") == ObjectId(profile_id) else None

    async def fake_get_pending_batch(profile_id_arg, batch_size):
        return [lead] if campaign_doc["pending"] > 0 else []

    async def fake_set_status(campaign_id_arg, new_status, employee_id_arg, is_admin):
        campaign_doc["status"] = new_status

    async def fake_finalize_campaign(campaign_id_arg):
        campaign_doc["status"] = "completed"
        campaign_doc["pending"] = 0

    async def fake_send_email(*args, **kwargs):
        return SimpleNamespace(success=True, thread_id=None, message_id="msg-1", error=None)

    async def fake_mark_sending(pe_id):
        return None

    async def fake_mark_sent(pe_id, thread_id, message_id, template_id=None):
        campaign_doc["sent"] += 1
        campaign_doc["pending"] = max(0, campaign_doc["pending"] - 1)

    async def fake_increment_counters(campaign_id_arg, sent=0, failed=0, skipped=0):
        campaign_doc["sent"] += sent
        campaign_doc["pending"] = max(0, campaign_doc["pending"] - sent)

    async def fake_get_credentials_for_send(gmail_account):
        return {"_id": str(ObjectId()), "email": "demo@gmail.com", "password": "secret", "displayName": "Demo", "smtpHost": "smtp.gmail.com", "smtpPort": 587, "useTls": True}

    def fake_build_email_payload(profile, lead):
        return {"to": lead["email"], "subject": "Hi Ada", "body": "Hello Ada", "html": "Hello Ada"}

    monkeypatch.setattr(worker, "get_collection", lambda name: FakeCampaignsCollection() if name == "campaigns" else FakeProfilesCollection())
    monkeypatch.setattr(worker, "get_credentials_for_send", fake_get_credentials_for_send)
    monkeypatch.setattr(worker, "send_email", fake_send_email)
    monkeypatch.setattr(worker.pe_service, "get_pending_batch", fake_get_pending_batch)
    monkeypatch.setattr(worker.pe_service, "mark_sending", fake_mark_sending)
    monkeypatch.setattr(worker.pe_service, "mark_sent", fake_mark_sent)
    monkeypatch.setattr(worker.campaign_service, "set_status", fake_set_status)
    monkeypatch.setattr(worker.campaign_service, "is_paused", AsyncMock(return_value=False))
    monkeypatch.setattr(worker.campaign_service, "increment_counters", fake_increment_counters)
    monkeypatch.setattr(worker.campaign_service, "finalize_campaign", fake_finalize_campaign)
    monkeypatch.setattr(worker, "_push_progress", AsyncMock())
    monkeypatch.setattr(worker, "record_send", AsyncMock())
    monkeypatch.setattr(worker, "record_sent", AsyncMock())
    monkeypatch.setattr(worker, "build_email_payload", fake_build_email_payload)

    asyncio.run(worker._run(campaign_id))

    assert campaign_doc["pending"] == 0
    assert campaign_doc["status"] == "completed"
    campaign_id = str(ObjectId())
    profile_id = str(ObjectId())
    employee_id = str(ObjectId())

    campaign_doc = {
        "_id": ObjectId(campaign_id),
        "campaignName": "Test campaign",
        "profileId": profile_id,
        "employeeId": employee_id,
        "dailyLimit": 1,
        "recurrenceType": "once",
        "status": "running",
        "totalEmails": 1,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "pending": 1,
    }

    profile_doc = {
        "_id": ObjectId(profile_id),
        "profileName": "Demo profile",
        "employeeId": employee_id,
        "gmailAccount": "demo@gmail.com",
        "sendingOptions": {"delayMin": 1, "delayMax": 1},
        "templates": [{"name": "Default", "subject": "Hi {{first_name}}", "body": "Hello {{first_name}}"}],
    }

    lead = {
        "id": str(ObjectId()),
        "email": "lead@example.com",
        "first_name": "Ada",
    }

    status_calls = []

    class FakeCampaignsCollection:
        async def find_one(self, query, *args, **kwargs):
            if query.get("_id") == ObjectId(campaign_id):
                return campaign_doc
            return None

    class FakeProfilesCollection:
        async def find_one(self, query, *args, **kwargs):
            if query.get("_id") == ObjectId(profile_id):
                return profile_doc
            return None

    async def fake_get_pending_batch(profile_id_arg, batch_size):
        if not hasattr(fake_get_pending_batch, "calls"):
            fake_get_pending_batch.calls = 0
        fake_get_pending_batch.calls += 1
        if fake_get_pending_batch.calls == 1:
            return [lead]
        return []

    async def fake_set_status(campaign_id_arg, new_status, employee_id_arg, is_admin):
        status_calls.append(new_status)

    async def fake_finalize_campaign(campaign_id_arg):
        campaign_doc["status"] = "completed"
        campaign_doc["pending"] = 0

    async def fake_record_send(account_id):
        return None

    async def fake_record_sent(employee_id_arg, count):
        return None

    async def fake_push_progress(*args, **kwargs):
        return None

    async def fake_send_email(*args, **kwargs):
        return SimpleNamespace(success=True, thread_id=None, message_id="msg-1", error=None)

    async def fake_mark_sending(pe_id):
        return None

    async def fake_mark_sent(pe_id, thread_id, message_id, template_id=None):
        return None

    async def fake_increment_counters(campaign_id_arg, sent=0, failed=0, skipped=0):
        campaign_doc["sent"] += sent
        campaign_doc["failed"] += failed
        campaign_doc["skipped"] += skipped
        campaign_doc["pending"] = max(0, campaign_doc["pending"] - (sent + failed + skipped))

    async def fake_get_credentials_for_send(gmail_account):
        return {
            "_id": str(ObjectId()),
            "email": "demo@gmail.com",
            "password": "secret",
            "displayName": "Demo",
            "smtpHost": "smtp.gmail.com",
            "smtpPort": 587,
            "useTls": True,
        }

    def fake_build_email_payload(profile, lead):
        return {
            "to": lead["email"],
            "subject": "Hi Ada",
            "body": "Hello Ada",
            "html": "Hello Ada",
        }

    monkeypatch.setattr(worker, "get_collection", lambda name: FakeCampaignsCollection() if name == "campaigns" else FakeProfilesCollection())
    monkeypatch.setattr(worker, "get_credentials_for_send", fake_get_credentials_for_send)
    monkeypatch.setattr(worker, "send_email", fake_send_email)
    monkeypatch.setattr(worker.pe_service, "get_pending_batch", fake_get_pending_batch)
    monkeypatch.setattr(worker.pe_service, "mark_sending", fake_mark_sending)
    monkeypatch.setattr(worker.pe_service, "mark_sent", fake_mark_sent)
    monkeypatch.setattr(worker.campaign_service, "set_status", fake_set_status)
    monkeypatch.setattr(worker.campaign_service, "is_paused", AsyncMock(return_value=False))
    monkeypatch.setattr(worker.campaign_service, "increment_counters", fake_increment_counters)
    monkeypatch.setattr(worker.campaign_service, "finalize_campaign", fake_finalize_campaign)
    monkeypatch.setattr(worker, "_push_progress", fake_push_progress)
    monkeypatch.setattr(worker, "record_send", fake_record_send)
    monkeypatch.setattr(worker, "record_sent", fake_record_sent)
    monkeypatch.setattr(worker, "build_email_payload", fake_build_email_payload)

    asyncio.run(worker._run(campaign_id))

    assert "paused" not in [s.value if hasattr(s, "value") else s for s in status_calls]
    assert campaign_doc["status"] == "completed"
