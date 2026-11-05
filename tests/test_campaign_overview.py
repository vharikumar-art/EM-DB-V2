import asyncio
from datetime import datetime, timedelta, timezone

from app.campaigns import service


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *_args):
        return self

    def __aiter__(self):
        self._iterator = iter(self.documents)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration


class FakeCampaignsCollection:
    def __init__(self, documents):
        self.documents = documents
        self.query = None

    def find(self, query):
        self.query = query
        return FakeCursor(
            [
                document
                for document in self.documents
                if document.get("employeeId") == query["employeeId"]
            ]
        )


def test_campaign_overview_aggregates_only_the_requested_employee_campaigns(monkeypatch):
    collection = FakeCampaignsCollection(
        [
            {
                "employeeId": "employee-1",
                "campaignName": "Summer Campaign",
                "status": "running",
                "totalEmails": 1000,
                "sent": 900,
                "pending": 100,
                "failed": 0,
                "skipped": 0,
            },
            {
                "employeeId": "employee-2",
                "campaignName": "Other employee campaign",
                "totalEmails": 50,
                "sent": 50,
                "pending": 0,
                "failed": 0,
                "skipped": 0,
            },
        ]
    )
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)

    result = asyncio.run(service.get_campaign_overview("employee-1"))

    assert collection.query == {"employeeId": "employee-1"}
    assert isinstance(result["summary"], str)
    assert "Campaigns: 1" in result["summary"]
    assert "Sent: 900" in result["summary"]
    assert "Pending: 100" in result["summary"]
    assert "Progress: 90%" in result["summary"]
    assert result["campaigns"] == "Summer Campaign is about to end."


def test_campaign_overview_returns_empty_alerts_without_campaigns(monkeypatch):
    collection = FakeCampaignsCollection([])
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)

    result = asyncio.run(service.get_campaign_overview("employee-1"))

    assert result["summary"] == (
        "Campaigns: 0 | Total emails: 0 | Sent: 0 | Pending: 0 | Failed: 0 | "
        "Skipped: 0 | Processed: 0 | Progress: 0%"
    )
    assert result["campaigns"] == ""


def test_campaign_overview_alerts_only_scheduled_campaigns_within_ten_minutes(
    monkeypatch,
):
    now = datetime.now(timezone.utc)
    collection = FakeCampaignsCollection(
        [
            {
                "employeeId": "employee-1",
                "campaignName": "Starts Soon",
                "status": "scheduled",
                "totalEmails": 100,
                "sent": 0,
                "pending": 100,
                "scheduledFor": now + timedelta(minutes=5),
            },
            {
                "employeeId": "employee-1",
                "campaignName": "Starts Later",
                "status": "scheduled",
                "totalEmails": 100,
                "sent": 0,
                "pending": 100,
                "scheduledFor": now + timedelta(minutes=15),
            },
            {
                "employeeId": "employee-1",
                "campaignName": "Already Started",
                "status": "running",
                "totalEmails": 100,
                "sent": 50,
                "pending": 50,
            },
        ]
    )
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)

    result = asyncio.run(service.get_campaign_overview("employee-1"))

    assert result["campaigns"] == "Starts Soon starts within 10 minutes."
    assert "Starts Later" not in result["campaigns"]
    assert "Already Started" not in result["campaigns"]


def test_campaign_overview_includes_multiple_alerts_and_omits_non_alert_details(
    monkeypatch,
):
    now = datetime.now(timezone.utc)
    collection = FakeCampaignsCollection(
        [
            {
                "employeeId": "employee-1",
                "campaignName": "Nearly Done",
                "status": "running",
                "totalEmails": 100,
                "sent": 85,
                "pending": 15,
            },
            {
                "employeeId": "employee-1",
                "campaignName": "Scheduled Soon",
                "status": "rescheduled",
                "totalEmails": 100,
                "sent": 0,
                "pending": 100,
                "scheduledFor": now + timedelta(minutes=2),
            },
            {
                "employeeId": "employee-1",
                "campaignName": "Completed",
                "status": "completed",
                "totalEmails": 100,
                "sent": 100,
                "pending": 0,
            },
        ]
    )
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)

    result = asyncio.run(service.get_campaign_overview("employee-1"))

    assert result["campaigns"] == (
        "Nearly Done is about to end.; "
        "Scheduled Soon starts within 10 minutes."
    )
    assert "Sent:" not in result["campaigns"]
    assert "Progress:" not in result["campaigns"]
