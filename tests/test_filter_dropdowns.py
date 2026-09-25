import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.email_master import service


class FilterDropdownTests(unittest.TestCase):
    def tearDown(self):
        service.invalidate_dropdown_cache()

    def test_update_flattens_domain_groups_and_uses_add_to_set(self):
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
        self.assertEqual(update["$addToSet"]["domains"], {"$each": ["Agriculture", "IT", "gmail.com"]})
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


if __name__ == "__main__":
    unittest.main()