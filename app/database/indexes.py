from app.database.mongodb import get_database


async def create_indexes() -> None:
    db = get_database()

    # ── users ────────────────────────────────────────────────────────────────
    await db["users"].create_index("email", unique=True)

    # ── employees ────────────────────────────────────────────────────────────
    await db["employees"].create_index("userId", unique=True)
    await db["employees"].create_index("employeeCode", unique=True, sparse=True)

    # ── email_master (permanent lead database) ───────────────────────────────
    await db["email_master"].create_index("email")
    await db["email_master"].create_index("employeeId")
    await db["email_master"].create_index("uploadBatch")
    await db["email_master"].create_index("isDuplicate")
    await db["email_master"].create_index("country")
    await db["email_master"].create_index("domain")
    await db["email_master"].create_index("industry")
    await db["email_master"].create_index("company")
    await db["email_master"].create_index("createdAt")
    await db["email_master"].create_index("usedByEmployeeId")
    await db["email_master"].create_index("inProfileEmails")
    # Dedup check is scoped per employee
    await db["email_master"].create_index(
        [("employeeId", 1), ("email", 1)], unique=True
    )
    # Index for finding emails used by specific employee
    await db["email_master"].create_index(
        [("usedByEmployeeId", 1), ("inProfileEmails", 1)]
    )

    # ── profiles ─────────────────────────────────────────────────────────────
    await db["profiles"].create_index("employeeId")
    await db["profiles"].create_index(
        [("employeeId", 1), ("profileName", 1)], unique=True
    )

    # ── profile_emails (working campaign table) ───────────────────────────────
    await db["profile_emails"].create_index("profileId")
    await db["profile_emails"].create_index("campaignId")
    await db["profile_emails"].create_index("employeeId")
    await db["profile_emails"].create_index("sendStatus")
    await db["profile_emails"].create_index("masterEmailId")
    await db["profile_emails"].create_index("email")
    await db["profile_emails"].create_index("createdAt")
    # Fast pending-batch fetch used by the campaign worker
    await db["profile_emails"].create_index(
        [("profileId", 1), ("sendStatus", 1), ("createdAt", 1)]
    )

    # ── campaigns ────────────────────────────────────────────────────────────
    await db["campaigns"].create_index("profileId")
    await db["campaigns"].create_index("employeeId")
    await db["campaigns"].create_index("status")
    await db["campaigns"].create_index("createdAt")
    await db["campaigns"].create_index(
        [("profileId", 1), ("status", 1)]
    )
    # Scheduling indexes - for Linux Cron scheduler to find due campaigns
    await db["campaigns"].create_index(
        [("status", 1), ("scheduledFor", 1)]
    )
    # Find campaigns due for execution: status='scheduled' AND scheduledFor <= now
    await db["campaigns"].create_index("scheduledFor")
    # Compound index for efficient query: find scheduled campaigns due for execution
    await db["campaigns"].create_index(
        [("status", 1), ("scheduledFor", 1), ("retryCount", 1)]
    )

    # ── templates ────────────────────────────────────────────────────────────
    await db["templates"].create_index("employeeId")
    await db["templates"].create_index("isGlobal")
    await db["templates"].create_index("tags")

    # ── email_accounts ───────────────────────────────────────────────────────
    await db["email_accounts"].create_index("employeeId")
    await db["email_accounts"].create_index(
        [("employeeId", 1), ("email", 1)], unique=True
    )

    # ── logs ─────────────────────────────────────────────────────────────────
    await db["logs"].create_index("employeeId")
    await db["logs"].create_index("profileId")
    await db["logs"].create_index("action")
    await db["logs"].create_index("createdAt")
    await db["logs"].create_index("runDate")

    # ── notifications ────────────────────────────────────────────────────────
    await db["notifications"].create_index("employeeId")
    await db["notifications"].create_index("isRead")
    await db["notifications"].create_index(
        [("employeeId", 1), ("isRead", 1), ("createdAt", -1)]
    )

    # ── auth (revoked tokens) ────────────────────────────────────────────────
    await db["revoked_tokens"].create_index("token", unique=True)
    await db["revoked_tokens"].create_index("userId")
