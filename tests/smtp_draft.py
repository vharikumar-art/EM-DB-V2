"""Manually send an SMTP integration-test email when explicitly enabled."""

import os
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid


def _required_setting(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Set {name} to run SMTP integration tests.")
    return value


def main() -> None:
    if os.getenv("RUN_SMTP_INTEGRATION_TESTS") != "1":
        raise RuntimeError(
            "Set RUN_SMTP_INTEGRATION_TESTS=1 to send an integration-test email."
        )

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    username = _required_setting("SMTP_USERNAME")
    password = _required_setting("SMTP_PASSWORD")
    sender = _required_setting("SMTP_SENDER_EMAIL")
    recipient = _required_setting("SMTP_TEST_RECIPIENT")

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = "SMTP integration test"
    message["Message-ID"] = make_msgid()
    message.set_content("This is an SMTP integration-test message.")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(username, password)
            server.send_message(message)
    elif port == 587:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(message)
    else:
        raise ValueError("SMTP_PORT must be 465 or 587.")

    print("SMTP integration-test email sent.")
    print("Message-ID:", message["Message-ID"])


if __name__ == "__main__":
    main()
