
# send_initial.py

import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

# ---------------- SMTP CONFIGURATION ----------------
SMTP_HOST = "smtp.gmail.com"       # Example: smtp.gmail.com
SMTP_PORT = 465      # 465 for SSL, or 587 for STARTTLS
SMTP_USERNAME = "vharikumar.art@gmail.com"
SMTP_PASSWORD = "qvzeeprmkgbjyvst"   # Gmail: use an App Password
SENDER_EMAIL = "vharikumar@gmail.com"
RECIPIENT_EMAIL = "saikrishnabit2003@gmail.com"

# ---------------- EMAIL CONTENT ----------------
SUBJECT = "Test email"
BODY = "This is a test email.If you receive this, please save the Message-ID printed in the console for sending a reminder."

# ---------------------------------------------------

msg = EmailMessage()
msg["From"] = SENDER_EMAIL
msg["To"] = RECIPIENT_EMAIL
msg["Subject"] = SUBJECT

# Generate and set the RFC Message-ID.
msg["Message-ID"] = make_msgid()
msg.set_content(BODY)

try:
    if SMTP_PORT == 465:
        # with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        #     server.login(SMTP_USERNAME, SMTP_PASSWORD)
        #     server.send_message(msg)
        with smtplib.SMTP_SSL(SMTP_HOST,465,timeout=30) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
            server.set_debuglevel(1)

            print("Connected to SMTP server")

            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            print("SMTP login successful")

            server.send_message(msg)
            print("Email submitted successfully")
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)

    print("Initial email sent successfully.")
    print("Save these values for the reminder:")
    print("Message-ID:", msg["Message-ID"])
    print("Subject:", SUBJECT)
    print("Recipient:", RECIPIENT_EMAIL)

except Exception as exc:
    print("Failed to send initial email:", exc)
