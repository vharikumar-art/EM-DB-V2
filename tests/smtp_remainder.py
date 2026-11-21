"""Manually send an SMTP reminder integration-test email when enabled."""

import os
import smtplib
from email.message import EmailMessage


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
    original_message_id = _required_setting("SMTP_ORIGINAL_MESSAGE_ID")
    original_subject = os.getenv("SMTP_ORIGINAL_SUBJECT", "SMTP integration test")
    references = os.getenv("SMTP_ORIGINAL_REFERENCES", "").strip()

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = (
        original_subject
        if original_subject.casefold().startswith("re:")
        else f"Re: {original_subject}"
    )
    message["In-Reply-To"] = original_message_id
    message["References"] = (
        f"{references} {original_message_id}"
        if references
        else original_message_id
    )
    message.set_content("This is an SMTP reminder integration-test message.")

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

    print("SMTP reminder integration-test email sent.")
    print("In-Reply-To:", message["In-Reply-To"])
    print("References:", message["References"])


if __name__ == "__main__":
    main()
