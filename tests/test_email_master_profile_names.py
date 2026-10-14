import asyncio
from bson import ObjectId

from app.email_master import service


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents

    def find(self, query, projection=None):
        async def matching_documents():
            if "masterEmailId" in query:
                master_ids = query["masterEmailId"]["$in"]
                matches = [
                    doc for doc in self.documents
                    if doc.get("masterEmailId") in master_ids
                ]
            else:
                profile_ids = query["_id"]["$in"]
                matches = [
                    doc for doc in self.documents
                    if doc.get("_id") in profile_ids
                ]
            for doc in matches:
                yield doc

        return matching_documents()


def test_enriches_email_master_rows_with_current_profile_names(monkeypatch):
    first_master_id = str(ObjectId())
    second_master_id = str(ObjectId())
    profile_id = ObjectId()
    deleted_profile_id = ObjectId()
    profile_email_docs = [
        {"masterEmailId": first_master_id, "profileId": str(profile_id)},
        {"masterEmailId": second_master_id, "profileId": str(deleted_profile_id)},
    ]
    profiles = [{"_id": profile_id, "profileName": "Active Profile"}]
    collections = {
        "profile_emails": FakeCollection(profile_email_docs),
        "profiles": FakeCollection(profiles),
    }
    monkeypatch.setattr(service, "get_collection", lambda name: collections[name])
    docs = [
        {"id": first_master_id, "inProfileEmails": False},
        {"id": second_master_id, "inProfileEmails": True},
        {"id": str(ObjectId()), "inProfileEmails": True},
    ]

    result = asyncio.run(service._enrich_emails_with_profile_names(docs))

    assert result[0]["profileNames"] == ["Active Profile"]
    assert result[0]["inProfileEmails"] is True
    assert result[1]["profileNames"] == []
    assert result[1]["inProfileEmails"] is False
    assert result[2]["profileNames"] == []
    assert result[2]["inProfileEmails"] is False
