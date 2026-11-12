"""Opt-in SMTP connectivity test; never contacts an SMTP server by default."""

import os
import smtplib

import pytest


def test_smtp_login():
    if os.getenv("RUN_SMTP_INTEGRATION_TESTS") != "1":
        pytest.skip("Set RUN_SMTP_INTEGRATION_TESTS=1 to enable SMTP integration tests.")

    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    if not username or not password:
        pytest.fail("SMTP_USERNAME and SMTP_PASSWORD must be configured.")

    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "465"))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as server:
            server.login(username, password)
    elif port == 587:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls()
            server.login(username, password)
    else:
        pytest.fail("SMTP_PORT must be 465 or 587.")
