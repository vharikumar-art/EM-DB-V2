
import smtplib
import socket
import traceback

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

SMTP_USERNAME = "vharikumar@gmail.com"
SMTP_PASSWORD = "qvzeeprmkgbjyvst"  # Enter your Google App Password

try:
    print("Step 1: Checking network connection...")

    with smtplib.SMTP_SSL(
        SMTP_HOST,
        SMTP_PORT,
        timeout=30
    ) as server:

        print("Step 2: SSL connection established.")
        server.set_debuglevel(1)

        print("Step 3: Testing SMTP login...")
        server.login(SMTP_USERNAME, SMTP_PASSWORD)

        print("Step 4: SMTP login successful.")

except (smtplib.SMTPException, OSError, socket.error) as exc:
    print("\nSMTP diagnostic failed.")
    print("Exception type:", type(exc).__name__)
    print("Exception details:", repr(exc))
    traceback.print_exc()
