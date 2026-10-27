
# send_reminder.py

import smtplib
from email.message import EmailMessage

# ---------------- SMTP CONFIGURATION ----------------
SMTP_HOST = "smtp.gmail.com"       # Example: smtp.gmail.com
SMTP_PORT = 465      # 465 for SSL, or 587 for STARTTLS
SMTP_USERNAME = "vharikumar.art@gmail.com"
SMTP_PASSWORD = "qvzeeprmkgbjyvst"
SENDER_EMAIL = "vharikumar@gmail.com"
RECIPIENT_EMAIL = "saikrishnabit2003@gmail.com"

# ---------------- ORIGINAL EMAIL DETAILS ----------------
ORIGINAL_SUBJECT = "Test email for reminder"

# Paste the exact Message-ID printed by send_initial.py
ORIGINAL_MESSAGE_ID = "<CAFQC8ctEfp4KogGPNFKfYfVDDPvWGY33LdME-veyUBenifT=sg@mail.gmail.com>"

# If the original email already had References headers,
# paste the existing References chain here. Otherwise leave blank.
ORIGINAL_REFERENCES = ""

# ---------------- REMINDER CONTENT ----------------
REMINDER_BODY = "This is a reminder email in reply to the original message. Please check your inbox for the initial email."

# ---------------------------------------------------

msg = EmailMessage()
msg["From"] = SENDER_EMAIL
msg["To"] = RECIPIENT_EMAIL

# Keep the original subject, adding Re: if needed.
if ORIGINAL_SUBJECT.lower().startswith("re:"):
    msg["Subject"] = ORIGINAL_SUBJECT
else:
    msg["Subject"] = f"Re: {ORIGINAL_SUBJECT}"

# Reply-threading headers
msg["In-Reply-To"] = ORIGINAL_MESSAGE_ID

references = ORIGINAL_REFERENCES.strip()
if references:
    references = f"{references} {ORIGINAL_MESSAGE_ID}"
else:
    references = ORIGINAL_MESSAGE_ID

msg["References"] = references
msg.set_content(REMINDER_BODY)

try:
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)

    print("Reminder email sent successfully.")
    print("In-Reply-To:", msg["In-Reply-To"])
    print("References:", msg["References"])

except Exception as exc:
    print("Failed to send reminder:", exc)
