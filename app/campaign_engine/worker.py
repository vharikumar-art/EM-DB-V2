"""
Campaign Engine Worker
======================
The main async send loop.  Triggered as a FastAPI BackgroundTask.

Flow per campaign:
  1. Load campaign document → load profile snapshot
  2. Fetch SMTP credentials for the profile's gmailAccount
  3. Fetch one batch of PENDING profile_emails
  4. For each lead:
       a. Mark as SENDING
       b. Personalize subject + body via LangChain personalizer
       c. Send over SMTP
       d. Mark SENT or FAILED
       e. Increment campaign counters (atomic)
       f. Push WebSocket progress notification
       g. Sleep random delay (delayMin–delayMax seconds)
       h. Check pause flag — if paused, exit loop (resume re-fires worker)
  5. When no more PENDING rows → finalize campaign (COMPLETED)

Error handling:
  - Per-email SMTP errors → mark FAILED, continue loop
  - Auth failure → abort entire campaign
  - Unhandled exception → abort campaign with error message
"""

import asyncio
import logging
import random

from app.campaign_engine.sender import SMTPCredentials, send_email
from app.campaigns import service as campaign_service
from app.campaigns.model import CampaignStatus
from app.database.mongodb import get_collection
from app.email_accounts.service import get_credentials_for_send, record_send
from app.langchain_service.personalizer import build_email_payload
from app.notifications.schema import NotificationType
from app.notifications.service import create_notification
from app.notifications.websocket import manager
from app.profile_emails import service as pe_service
from app.utils.response import serialize_doc, to_object_id

logger = logging.getLogger("campaign_engine.worker")

# How many profile_emails to load per iteration (keeps memory bounded)
BATCH_SIZE = 50

# How many consecutive auth failures before aborting
MAX_AUTH_FAILURES = 3


async def run_campaign(campaign_id: str) -> None:
    """
    Entry point called by the campaigns router via BackgroundTasks.
    All exceptions are caught here so they never crash the FastAPI process.
    """
    try:
        await _run(campaign_id)
    except Exception as exc:
        logger.exception("Unhandled error in campaign %s: %s", campaign_id, exc)
        await campaign_service.abort_campaign(campaign_id, str(exc)[:300])


async def _run(campaign_id: str) -> None:
    # ------------------------------------------------------------------
    # 1. Load campaign + profile
    # ------------------------------------------------------------------
    campaigns_col = get_collection("campaigns")
    campaign_doc = await campaigns_col.find_one({"_id": to_object_id(campaign_id)})
    if not campaign_doc:
        logger.error("Campaign %s not found", campaign_id)
        return

    campaign = serialize_doc(campaign_doc)
    profile_id: str = campaign["profileId"]
    employee_id: str = campaign["employeeId"]

    # Load live profile (subject/body/signature/sendingOptions/promptSettings)
    profiles_col = get_collection("profiles")
    profile_doc = await profiles_col.find_one({"_id": to_object_id(profile_id)})
    if not profile_doc:
        await campaign_service.abort_campaign(campaign_id, "Profile not found")
        return

    profile = serialize_doc(profile_doc)
    sending_opts = profile.get("sendingOptions", {})
    delay_min: int = max(int(sending_opts.get("delayMin", 30)), 5)
    delay_max: int = max(int(sending_opts.get("delayMax", 90)), delay_min)
    gmail_account: str = profile["gmailAccount"]

    # ------------------------------------------------------------------
    # 2. Load SMTP credentials
    # ------------------------------------------------------------------
    try:
        creds_data = await get_credentials_for_send(gmail_account)
    except Exception as exc:
        await campaign_service.abort_campaign(campaign_id, str(exc))
        return

    credentials = SMTPCredentials(
        email=creds_data["email"],
        password=creds_data["password"],
        display_name=creds_data.get("displayName", creds_data["email"]),
        smtp_host=creds_data["smtpHost"],
        smtp_port=creds_data["smtpPort"],
        use_tls=creds_data["useTls"],
    )
    account_id: str = creds_data["_id"]

    # ------------------------------------------------------------------
    # 3. Transition to RUNNING
    # ------------------------------------------------------------------
    try:
        await campaign_service.set_status(
            campaign_id, CampaignStatus.RUNNING, employee_id, is_admin=True
        )
    except Exception:
        # Already running (resume path) — that's fine
        pass

    logger.info(
        "Campaign %s started | profile=%s | account=%s",
        campaign_id, profile_id, gmail_account,
    )

    # ------------------------------------------------------------------
    # 4. Send loop
    # ------------------------------------------------------------------
    auth_failure_count = 0
    total_sent = 0
    total_failed = 0

    while True:
        # Respect pause
        if await campaign_service.is_paused(campaign_id):
            logger.info("Campaign %s paused — exiting worker", campaign_id)
            return

        # Fetch next batch of PENDING emails
        batch = await pe_service.get_pending_batch(profile_id, BATCH_SIZE)
        if not batch:
            logger.info(
                "Campaign %s — no more pending emails. Finalizing.", campaign_id
            )
            break

        for pe in batch:
            # Re-check pause between individual sends
            if await campaign_service.is_paused(campaign_id):
                logger.info("Campaign %s paused mid-batch — exiting worker", campaign_id)
                return

            pe_id: str = pe["id"]
            lead_email: str = pe["email"]

            # Mark as SENDING
            await pe_service.mark_sending(pe_id)

            # ----------------------------------------------------------
            # Personalize with LangChain (placeholder replacement only)
            # ----------------------------------------------------------
            try:
                payload = build_email_payload(profile=profile, lead=pe)
            except Exception as exc:
                logger.warning(
                    "Personalization failed for %s: %s — using raw template", lead_email, exc
                )
                payload = {
                    "to": lead_email,
                    "subject": profile.get("subject", "(no subject)"),
                    "body": profile.get("body", ""),
                    "html": profile.get("body", "").replace("\n", "<br>"),
                }

            # ----------------------------------------------------------
            # Send
            # ----------------------------------------------------------
            result = await send_email(
                credentials=credentials,
                to=payload["to"],
                subject=payload["subject"],
                body_plain=payload["body"],
                body_html=payload["html"],
            )

            if result.success:
                await pe_service.mark_sent(pe_id, result.thread_id, result.message_id)
                await campaign_service.increment_counters(campaign_id, sent=1)
                await record_send(account_id)
                total_sent += 1
                auth_failure_count = 0  # reset on success

                # Live progress push via WebSocket
                await _push_progress(
                    employee_id=employee_id,
                    campaign_id=campaign_id,
                    event="sent",
                    email=lead_email,
                    total_sent=total_sent,
                    total_failed=total_failed,
                )

            else:
                error_msg = result.error or "Unknown send error"
                await pe_service.mark_failed(pe_id, error_msg)
                await campaign_service.increment_counters(campaign_id, failed=1)
                total_failed += 1

                # Auth failure → abort entire campaign immediately
                if "Authentication" in error_msg or "auth" in error_msg.lower():
                    auth_failure_count += 1
                    if auth_failure_count >= MAX_AUTH_FAILURES:
                        logger.error(
                            "Campaign %s aborted — repeated auth failures for %s",
                            campaign_id, gmail_account,
                        )
                        await campaign_service.abort_campaign(
                            campaign_id,
                            f"Authentication failed for {gmail_account}. "
                            "Check your Gmail App Password in Email Accounts settings.",
                        )
                        return

                # Push failure notification (throttled — only every 10 failures)
                if total_failed % 10 == 1:
                    await create_notification(
                        employee_id=employee_id,
                        message=f"Campaign: {total_failed} email(s) failed so far. Last error: {error_msg[:100]}",
                        type=NotificationType.WARNING,
                    )

            # ----------------------------------------------------------
            # Random delay between sends
            # ----------------------------------------------------------
            delay_seconds = random.randint(delay_min, delay_max)
            logger.debug(
                "Campaign %s — waiting %ds before next send", campaign_id, delay_seconds
            )
            await asyncio.sleep(delay_seconds)

        # End of batch — loop back to fetch next batch

    # ------------------------------------------------------------------
    # 5. Finalize
    # ------------------------------------------------------------------
    await campaign_service.finalize_campaign(campaign_id)
    logger.info(
        "Campaign %s completed — sent=%d, failed=%d",
        campaign_id, total_sent, total_failed,
    )


async def _push_progress(
    employee_id: str,
    campaign_id: str,
    event: str,
    email: str,
    total_sent: int,
    total_failed: int,
) -> None:
    """
    Push a lightweight real-time progress event via the existing WebSocket manager.
    The frontend listens on the same notifications WebSocket channel.
    """
    message = {
        "type": "campaign_progress",
        "campaignId": campaign_id,
        "event": event,        # "sent" | "failed"
        "email": email,
        "totalSent": total_sent,
        "totalFailed": total_failed,
    }
    try:
        await manager.send_personal_message(message, employee_id)
        await manager.broadcast_to_admins(message, exclude_channel=employee_id)
    except Exception:
        pass  # WebSocket push is best-effort — never crash the send loop
