import asyncio

from app.campaigns import service
from app.schemas.common import PaginationParams


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *_args):
        return self

    def skip(self, count):
        self.documents = self.documents[count:]
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
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
    def __init__(self):
        self.documents = [
            {"campaignName": "Completed campaign", "status": "completed"},
            {"campaignName": "Paused campaign", "status": "paused"},
        ]

    async def count_documents(self, query):
        return len(self._matching_documents(query))

    def find(self, query):
        return FakeCursor(self._matching_documents(query))

    def _matching_documents(self, query):
        status = query.get("status")
        return [
            document
            for document in self.documents
            if status is None or document["status"] == status
        ]


def test_campaign_list_treats_all_sentinel_as_no_status_filter(monkeypatch):
    collection = FakeCampaignsCollection()
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)

    for status in ("all", "All", "1", None):
        result = asyncio.run(
            service.list_campaigns(
                employee_id=None,
                params=PaginationParams(page=1, pageSize=25),
                status_filter=status,
            )
        )

        assert result.total == 2
        assert {campaign["status"] for campaign in result.data} == {
            "completed",
            "paused",
        }


def test_campaign_list_keeps_real_status_filter(monkeypatch):
    collection = FakeCampaignsCollection()
    monkeypatch.setattr(service, "get_collection", lambda _name: collection)

    result = asyncio.run(
        service.list_campaigns(
            employee_id=None,
            params=PaginationParams(page=1, pageSize=25),
            status_filter="Paused",
        )
    )

    assert result.total == 1
    assert result.data[0]["status"] == "paused"
