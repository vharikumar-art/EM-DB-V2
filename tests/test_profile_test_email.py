import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.profiles import service
from app.profiles.schema import ProfileTestEmailRequest


class ProfileTestEmailTests(unittest.TestCase):
    def test_send_test_email_uses_profile_sender_template_and_attachments(self):
        profile_doc = {
            "_id": "64f1e9d0a1b2c3d4e5f60789",
            "employeeId": "emp_1",
            "gmailAccount": "sender@example.com",
            "signature": "<p>Thanks</p>",
            "templates": [
                {
                    "id": "template_1",
                    "name": "Welcome",
                    "subject": "Hello [name]",
                    "body": "Hi [name], this is a test email.",
                    "attachments": [
                        {"filename": "template.pdf", "filepath": "uploads/templates/template.pdf"}
                    ],
                }
            ],
            "attachments": [
                {"filename": "profile.pdf", "filepath": "uploads/profiles/profile.pdf"}
            ],
        }

        def fake_get_collection(collection_name):
            class FakeCollection:
                async def find_one(self, query, *args, **kwargs):
                    if collection_name == "profiles":
                        return profile_doc
                    return None
            return FakeCollection()

        with patch.object(service, "get_collection", side_effect=fake_get_collection):
            with patch.object(
                service,
                "get_credentials_for_send",
                new=AsyncMock(
                    return_value={
                        "email": "sender@example.com",
                        "password": "secret",
                        "displayName": "Sender",
                        "smtpHost": "smtp.gmail.com",
                        "smtpPort": 587,
                        "useTls": True,
                    }
                ),
            ):
                with patch.object(service, "send_email", new=AsyncMock(return_value=type("R", (), {"success": True, "message_id": "msg_123", "error": ""})())) as mock_send:
                    result = asyncio.run(
                        service.send_test_email(
                            "64f1e9d0a1b2c3d4e5f60789",
                            "emp_1",
                            False,
                            ProfileTestEmailRequest(toEmail="receiver@example.com", templateId="template_1"),
                        )
                    )

        self.assertTrue(result["success"])
        self.assertEqual(result["fromEmail"], "sender@example.com")
        self.assertEqual(result["toEmail"], "receiver@example.com")
        self.assertEqual(len(mock_send.await_args.kwargs["attachments"]), 2)
        self.assertEqual(mock_send.await_args.kwargs["subject"], "Hello Test")

    def test_send_test_email_selects_reminder_template(self):
        profile_doc = {
            "_id": "64f1e9d0a1b2c3d4e5f60789",
            "employeeId": "emp_1",
            "gmailAccount": "sender@example.com",
            "signature": "<p>Thanks</p>",
            "templates": [{"subject": "Original subject for [name]"}],
            "reminderTemplates": [
                {
                    "id": "reminder_1",
                    "name": "Follow-up",
                    "body": "Hello [name], following up.",
                    "weight": 1,
                }
            ],
            "attachments": [],
        }

        class FakeCollection:
            async def find_one(self, *_args, **_kwargs):
                return profile_doc

        with patch.object(service, "get_collection", return_value=FakeCollection()):
            with patch.object(
                service, "_assert_owns_profile_or_admin", new=AsyncMock()
            ):
                with patch.object(
                    service,
                    "get_credentials_for_send",
                    new=AsyncMock(
                        return_value={
                            "email": "sender@example.com",
                            "password": "secret",
                            "displayName": "Sender",
                            "smtpHost": "smtp.gmail.com",
                            "smtpPort": 587,
                            "useTls": True,
                        }
                    ),
                ):
                    with patch.object(
                        service,
                        "send_email",
                        new=AsyncMock(
                            return_value=type(
                                "R",
                                (),
                                {
                                    "success": True,
                                    "message_id": "msg_456",
                                    "error": "",
                                },
                            )()
                        ),
                    ) as mock_send:
                        result = asyncio.run(
                            service.send_test_email(
                                "64f1e9d0a1b2c3d4e5f60789",
                                "emp_1",
                                False,
                                ProfileTestEmailRequest(
                                    toEmail="receiver@example.com",
                                    mailType="reminder",
                                    templateId="reminder_1",
                                ),
                            )
                        )

        self.assertTrue(result["success"])
        self.assertEqual(result["mailType"], "reminder")
        self.assertEqual(result["templateId"], "reminder_1")
        self.assertEqual(result["subject"], "Original subject for Test")
        self.assertEqual(
            mock_send.await_args.kwargs["body_plain"],
            "Hello Test, following up.",
        )
        self.assertIn("<p>Thanks</p>", mock_send.await_args.kwargs["body_html"])


if __name__ == "__main__":
    unittest.main()
