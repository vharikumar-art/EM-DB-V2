"""
SMTP Sender
===========
Handles the actual email dispatch over Gmail SMTP (or any SMTP server).

Returns a SendResult containing the thread/message-id extracted from the
SMTP server response so the campaign engine can track every send.
"""

import asyncio
import logging
import smtplib
import uuid
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger("campaign_engine.sender")


@dataclass
class SendResult:
    success: bool
    message_id: str = ""
    thread_id: str = ""      # Gmail uses Message-ID as thread anchor for first mail
    error: str = ""


@dataclass
class SMTPCredentials:
    email: str
    password: str
    display_name: str
    smtp_host: str
    smtp_port: int
    use_tls: bool


def _build_mime_message(
    credentials: SMTPCredentials,
    to: str,
    subject: str,
    body_plain: str,
    body_html: str,
    message_id: str,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["From"] = (
        f"{credentials.display_name} <{credentials.email}>"
        if credentials.display_name
        else credentials.email
    )
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = message_id

    # Attach both plain-text and HTML parts; mail clients prefer HTML
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    return msg


def _send_sync(
    credentials: SMTPCredentials,
    to: str,
    subject: str,
    body_plain: str,
    body_html: str,
) -> SendResult:
    """
    Synchronous SMTP send.  Called from a thread pool by the async wrapper
    so it never blocks the event loop.
    """
    message_id = f"<{uuid.uuid4().hex}@{credentials.email.split('@')[1]}>"
    msg = _build_mime_message(credentials, to, subject, body_plain, body_html, message_id)

    try:
        if credentials.use_tls:
            server = smtplib.SMTP(credentials.smtp_host, credentials.smtp_port, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP_SSL(credentials.smtp_host, credentials.smtp_port, timeout=30)

        server.login(credentials.email, credentials.password)
        server.sendmail(credentials.email, [to], msg.as_string())
        server.quit()

        logger.info("Sent → %s | subject: %s | message_id: %s", to, subject[:60], message_id)
        return SendResult(
            success=True,
            message_id=message_id,
            # Gmail groups replies by Message-ID of the first message in the thread
            thread_id=message_id,
        )

    except smtplib.SMTPAuthenticationError as exc:
        error = f"Authentication failed: {exc}"
        logger.error("SMTP auth error sending to %s: %s", to, error)
        return SendResult(success=False, error=error)

    except smtplib.SMTPRecipientsRefused as exc:
        error = f"Recipient refused: {exc}"
        logger.warning("Recipient refused %s: %s", to, error)
        return SendResult(success=False, error=error)

    except smtplib.SMTPException as exc:
        error = f"SMTP error: {exc}"
        logger.error("SMTP error sending to %s: %s", to, error)
        return SendResult(success=False, error=error)

    except OSError as exc:
        error = f"Connection error: {exc}"
        logger.error("Connection error sending to %s: %s", to, error)
        return SendResult(success=False, error=error)


async def send_email(
    credentials: SMTPCredentials,
    to: str,
    subject: str,
    body_plain: str,
    body_html: str,
) -> SendResult:
    """
    Async wrapper — runs the blocking SMTP call in a thread pool
    so the FastAPI event loop is never blocked.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,  # default ThreadPoolExecutor
        _send_sync,
        credentials,
        to,
        subject,
        body_plain,
        body_html,
    )
    return result
