import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bson import ObjectId

from app.core.exceptions import BadRequestException
from app.email_master import service


class FakeCursor:
    def __init__(self, documents):
        self.documents = documents

    def batch_size(self, _size):
        return self

    def sort(self, field, direction=1):
        self.documents.sort(
            key=lambda document: document[field],
            reverse=direction < 0,
        )
        return self

    def limit(self, size):
        self.documents = self.documents[:size]
        return self

    async def to_list(self, length=None):
        return self.documents if length is None else self.documents[:length]

    def __aiter__(self):
        async def iterate():
            for document in self.documents:
                yield document

        return iterate()


def matches(document, query):
    for field, expected in query.items():
        if field == "$and":
            if not all(matches(document, clause) for clause in expected):
                return False
            continue
        actual = document.get(field)
        if isinstance(expected, re.Pattern):
            if not isinstance(actual, str) or expected.search(actual) is None:
                return False
        elif isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$gt" in expected and not actual > expected["$gt"]:
                return False
            if "$exists" in expected and ((field in document) != expected["$exists"]):
                return False
            if "$eq" in expected and actual != expected["$eq"]:
                return False
        elif actual != expected:
            return False
    return True


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents

    def find(self, query, _projection=None):
        return FakeCursor(
            [document for document in self.documents if matches(document, query)]
        )

    async def bulk_write(self, operations, ordered=False):
        matched_count = 0
        modified_count = 0
        for operation in operations:
            for document in self.documents:
                if matches(document, operation._filter):
                    matched_count += 1
                    updates = operation._doc["$set"]
                    if any(document.get(key) != value for key, value in updates.items()):
                        document.update(updates)
                        modified_count += 1
                    break
        return SimpleNamespace(
            matched_count=matched_count,
            modified_count=modified_count,
        )


def make_collections():
    first_master_id = ObjectId()
    conflict_master_id = ObjectId()
    master = FakeCollection(
        [
            {
                "_id": first_master_id,
                "country": "TAMIL NADU",
                "state": "",
            },
            {
                "_id": conflict_master_id,
                "country": "TAMIL NADU",
                "state": "KERALA",
            },
        ]
    )
    profiles = FakeCollection(
        [
            {
                "_id": ObjectId(),
                "masterEmailId": str(first_master_id),
                "country": "TAMIL NADU",
                "state": "",
            },
            {
                "_id": ObjectId(),
                "masterEmailId": str(conflict_master_id),
                "country": "TAMIL NADU",
                "state": "KERALA",
            },
        ]
    )
    return master, profiles


def run_update(monkeypatch, overwrite):
    master, profiles = make_collections()
    collections = {
        service.COLLECTION: master,
        "profile_emails": profiles,
    }
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: collections[name],
    )
    monkeypatch.setattr(
        service,
        "rebuild_dropdown_filters",
        AsyncMock(return_value={"countries": 1, "states": 1}),
    )
    result = asyncio.run(
        service.update_filter_value(
            {
                "sourceField": "country",
                "sourceValue": "TAMIL NADU",
                "targetField": "state",
                "targetValue": None,
                "overwrite": overwrite,
            }
        )
    )
    return result, master.documents, profiles.documents


def test_move_skips_records_with_a_populated_destination(monkeypatch):
    result, master_docs, profile_docs = run_update(monkeypatch, overwrite=False)

    assert result["matched"] == 2
    assert result["changed"] == 1
    assert result["skipped"] == 1
    assert result["profileEmailsChanged"] == 1
    assert master_docs[0]["country"] == ""
    assert master_docs[0]["state"] == "TAMIL NADU"
    assert master_docs[1]["country"] == "TAMIL NADU"
    assert master_docs[1]["state"] == "KERALA"
    assert profile_docs[0]["state"] == "TAMIL NADU"
    assert profile_docs[1]["state"] == "KERALA"


def test_move_overwrites_populated_destination_when_requested(monkeypatch):
    monkeypatch.setattr(service, "FILTER_UPDATE_BATCH_SIZE", 1)
    result, master_docs, profile_docs = run_update(monkeypatch, overwrite=True)

    assert result["matched"] == 2
    assert result["changed"] == 2
    assert result["skipped"] == 0
    assert result["overwritten"] == 1
    assert result["profileEmailsChanged"] == 2
    assert all(document["country"] == "" for document in master_docs)
    assert all(document["state"] == "TAMIL NADU" for document in master_docs)
    assert all(document["country"] == "" for document in profile_docs)
    assert all(document["state"] == "TAMIL NADU" for document in profile_docs)


def test_rename_updates_master_and_linked_profile_email(monkeypatch):
    master_id = ObjectId()
    master = FakeCollection([{"_id": master_id, "state": "TAMILNADU"}])
    profiles = FakeCollection(
        [
            {
                "_id": ObjectId(),
                "masterEmailId": str(master_id),
                "state": "TAMILNADU",
            }
        ]
    )
    collections = {
        service.COLLECTION: master,
        "profile_emails": profiles,
    }
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: collections[name],
    )
    monkeypatch.setattr(
        service,
        "rebuild_dropdown_filters",
        AsyncMock(return_value={"countries": 1, "states": 1}),
    )

    result = asyncio.run(
        service.update_filter_value(
            {
                "sourceField": "state",
                "sourceValue": "tamilnadu",
                "targetField": "state",
                "targetValue": "Tamil Nadu",
            }
        )
    )

    assert result["matched"] == 1
    assert result["changed"] == 1
    assert result["skipped"] == 0
    assert master.documents[0]["state"] == "TAMIL NADU"
    assert profiles.documents[0]["state"] == "TAMIL NADU"


def test_same_field_rename_requires_a_target_value(monkeypatch):
    with patch.object(service, "get_collection") as get_collection:
        try:
            asyncio.run(
                service.update_filter_value(
                    {
                        "sourceField": "state",
                        "sourceValue": "TAMILNADU",
                        "targetField": "state",
                        "targetValue": None,
                    }
                )
            )
        except BadRequestException as exc:
            assert "targetValue is required" in exc.detail
        else:
            raise AssertionError("Expected a validation error")
    get_collection.assert_not_called()


def test_domain_university_and_city_can_move_between_fields(monkeypatch):
    field_pairs = [
        ("domain", "city"),
        ("university", "country"),
        ("city", "university"),
    ]

    for source_field, target_field in field_pairs:
        master_id = ObjectId()
        master = FakeCollection(
            [{"_id": master_id, source_field: "SOURCE VALUE", target_field: ""}]
        )
        profiles = FakeCollection(
            [
                {
                    "_id": ObjectId(),
                    "masterEmailId": str(master_id),
                    source_field: "SOURCE VALUE",
                    target_field: "",
                }
            ]
        )
        collections = {
            service.COLLECTION: master,
            "profile_emails": profiles,
        }
        monkeypatch.setattr(
            service,
            "get_collection",
            lambda name: collections[name],
        )
        monkeypatch.setattr(
            service,
            "rebuild_dropdown_filters",
            AsyncMock(return_value={}),
        )

        result = asyncio.run(
            service.update_filter_value(
                {
                    "sourceField": source_field,
                    "sourceValue": "SOURCE VALUE",
                    "targetField": target_field,
                }
            )
        )

        assert result["changed"] == 1
        assert result["skipped"] == 0
        assert master.documents[0][source_field] == ""
        assert master.documents[0][target_field] == "SOURCE VALUE"
        assert profiles.documents[0][source_field] == ""
        assert profiles.documents[0][target_field] == "SOURCE VALUE"
