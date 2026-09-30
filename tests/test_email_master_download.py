import asyncio
from unittest.mock import patch

from app.email_master import router


class FakeCursor:
    def __init__(self, docs):
        self.docs = iter(docs)

    def sort(self, *_args):
        return self

    def batch_size(self, *_args):
        return self

    async def to_list(self, length):
        batch = []
        for _ in range(length):
            try:
                batch.append(next(self.docs))
            except StopIteration:
                break
        return batch


class FakeMaster:
    def find(self, *_args):
        return FakeCursor([
            {"email": "one@example.com", "fullName": "One"},
            {"email": "two@example.com", "fullName": "Two"},
        ])


def test_csv_download_streams_header_once_and_all_rows():
    async def run():
        with patch.object(router.service, "get_collection", return_value=FakeMaster()):
            response = await router.download_emails(
                format="csv",
                country=None,
                state=None,
                domain=None,
                university=None,
                mailSource=None,
                search=None,
                includeDuplicates=True,
                current_user=None,
            )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    csv_text = asyncio.run(run())
    assert csv_text.count("fullName,email,") == 1
    assert "One,one@example.com" in csv_text
    assert "Two,two@example.com" in csv_text
