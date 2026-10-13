import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.email_master import service


class FilterDropdownTests(unittest.TestCase):
    def tearDown(self):
        service.invalidate_dropdown_cache()

    def test_update_uses_only_domain_field_for_domain_dropdown(self):
        collection = type("Collection", (), {"update_one": AsyncMock()})()
        docs = [
            {
                "domain": "gmail.com",
                "domain_group": ["IT", "Agriculture"],
                "country": "USA",
                "mailSource": "Campaign A",
            },
            {
                "domain": "gmail.com",
                "domain_group": ["Agriculture"],
                "country": "USA",
            },
        ]

        with patch.object(service, "get_collection", return_value=collection):
            asyncio.run(service._update_dropdown_filters(docs, "user-1", "Uploader"))

        query, update = collection.update_one.await_args.args
        self.assertEqual(query, {"_id": "global"})
        self.assertEqual(update["$addToSet"]["domains"], {"$each": ["gmail.com"]})
        self.assertEqual(update["$addToSet"]["countries"], {"$each": ["USA"]})
        self.assertEqual(update["$addToSet"]["uploaders"], {"id": "user-1", "name": "Uploader"})

    def test_get_dropdown_options_reads_document_without_distinct(self):
        collection = type(
            "Collection",
            (),
            {"find_one": AsyncMock(return_value={"_id": "global", "domains": ["gmail.com"], "internal": ["ignored"]})},
        )()

        with patch.object(service, "get_collection", return_value=collection):
            result = asyncio.run(service.get_dropdown_options())

        self.assertEqual(result["domains"], ["gmail.com"])
        self.assertNotIn("internal", result)
        collection.find_one.assert_awaited_once_with({"_id": "global"})

    def test_rebuild_dropdowns_uses_domain_without_domain_group(self):
        aggregate_cursor = type(
            "AggregateCursor",
            (),
            {"to_list": AsyncMock(return_value=[{"domains": ["gmail.com"]}])},
        )()

        class MasterCollection:
            def aggregate(self, pipeline):
                self.pipeline = pipeline
                return aggregate_cursor

            def find(self, query, projection):
                async def documents():
                    yield {
                        "uploadedBy": "user-1",
                        "uploadedByName": "Uploader",
                    }

                return documents()

        class FilterCollection:
            async def replace_one(self, query, replacement, upsert=False):
                self.replacement = replacement

        master = MasterCollection()
        filters = FilterCollection()
        with patch.object(
            service,
            "get_collection",
            side_effect=lambda name: master if name == service.COLLECTION else filters,
        ):
            result = asyncio.run(service.rebuild_dropdown_filters())

        group_fields = master.pipeline[0]["$group"]
        self.assertIn("domains", group_fields)
        self.assertNotIn("domain_groups", group_fields)
        self.assertEqual(filters.replacement["domains"], ["gmail.com"])
        self.assertEqual(result["domains"], 1)


if __name__ == "__main__":
    unittest.main()