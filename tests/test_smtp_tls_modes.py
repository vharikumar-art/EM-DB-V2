import unittest
from unittest.mock import Mock, patch

from app.email_accounts.service import _smtp_login_check


class SmtpTlsModeTests(unittest.TestCase):
    @patch("app.email_accounts.service.smtplib.SMTP_SSL")
    @patch("app.email_accounts.service.smtplib.SMTP")
    def test_port_465_uses_implicit_tls(self, smtp, smtp_ssl):
        server = Mock()
        smtp_ssl.return_value = server

        _smtp_login_check("smtp.zoho.in", 465, "sender@example.com", "secret", True)

        smtp.assert_not_called()
        smtp_ssl.assert_called_once_with("smtp.zoho.in", 465, timeout=10)
        server.starttls.assert_not_called()
        server.login.assert_called_once_with("sender@example.com", "secret")
        server.quit.assert_called_once_with()

    @patch("app.email_accounts.service.smtplib.SMTP_SSL")
    @patch("app.email_accounts.service.smtplib.SMTP")
    def test_port_587_uses_starttls(self, smtp, smtp_ssl):
        server = Mock()
        smtp.return_value = server

        _smtp_login_check("smtp.gmail.com", 587, "sender@example.com", "secret", True)

        smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
        smtp_ssl.assert_not_called()
        server.starttls.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()