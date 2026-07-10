from datetime import datetime, timedelta, timezone

from app.dashboard.schema import DashboardQuery
from app.dashboard.utils import resolve_date_range
from app.database.mongodb import get_collection
from app.utils.response import serialize_list


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_oid(id_str: str):
    from bson import ObjectId
    return ObjectId(id_str) if ObjectId.is_valid(id_str) else None


async def _employee_name(employee_id: str) -> str:
    employees = get_collection("employees")
    emp = await employees.find_one({"_id": _safe_oid(employee_id)})
    if not emp:
        return "Unknown"
    users = get_collection("users")
    user = await users.find_one({"_id": _safe_oid(str(emp["userId"]))})
    return user["name"] if user else "Unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Employee dashboard
# ─────────────────────────────────────────────────────────────────────────────

async def get_employee_dashboard(employee_id: str, query: DashboardQuery) -> dict:
    master     = get_collection("email_master")
    pe_col     = get_collection("profile_emails")
    campaigns  = get_collection("campaigns")
    profiles   = get_collection("profiles")
    logs       = get_collection("logs")

    now         = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last_7_start = today_start - timedelta(days=6)
    start_dt, end_dt = resolve_date_range(query)

    # ── Upload counts ────────────────────────────────────────────────────────
    today_uploads  = await master.count_documents(
        {"employeeId": employee_id, "createdAt": {"$gte": today_start}}
    )
    last_7_uploads = await master.count_documents(
        {"employeeId": employee_id, "createdAt": {"$gte": last_7_start}}
    )
    total_uploads  = await master.count_documents(
        {"employeeId": employee_id, "createdAt": {"$gte": start_dt, "$lte": end_dt}}
    )
    unique_emails  = await master.count_documents(
        {
            "employeeId": employee_id,
            "isDuplicate": False,
            "createdAt": {"$gte": start_dt, "$lte": end_dt},
        }
    )

    # ── Campaign counts ──────────────────────────────────────────────────────
    active_profiles  = await profiles.count_documents(
        {"employeeId": employee_id, "isActive": True}
    )
    total_campaigns  = await campaigns.count_documents({"employeeId": employee_id})
    running_campaigns = await campaigns.count_documents(
        {"employeeId": employee_id, "status": "running"}
    )

    # ── Sent today (profile_emails) ──────────────────────────────────────────
    sent_today = await pe_col.count_documents(
        {
            "employeeId": employee_id,
            "sendStatus": "sent",
            "sentDate": {"$gte": today_start},
        }
    )

    # ── Aggregate pending / failed across all profiles ───────────────────────
    pending_total = await pe_col.count_documents(
        {"employeeId": employee_id, "sendStatus": "pending"}
    )
    failed_total  = await pe_col.count_documents(
        {"employeeId": employee_id, "sendStatus": "failed"}
    )

    # ── Total sent (range) from logs ─────────────────────────────────────────
    sent_pipeline = [
        {
            "$match": {
                "employeeId": employee_id,
                "action": "CAMPAIGN_COMPLETED",
                "runDate": {"$gte": start_dt, "$lte": end_dt},
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$sentCount"}}},
    ]
    sent_result = await logs.aggregate(sent_pipeline).to_list(length=1)
    sent_total  = sent_result[0]["total"] if sent_result else 0

    # ── Success rate ─────────────────────────────────────────────────────────
    delivered = await pe_col.count_documents(
        {"employeeId": employee_id, "sendStatus": "sent"}
    )
    attempted = delivered + failed_total
    success_rate = round((delivered / attempted * 100), 1) if attempted > 0 else 0.0

    # ── Daily limit (from first active profile found) ─────────────────────────
    first_profile = await profiles.find_one(
        {"employeeId": employee_id, "isActive": True}
    )
    daily_limit = (
        first_profile.get("sendingOptions", {}).get("dailyLimit", 100)
        if first_profile
        else 100
    )

    # ── Profile statistics ───────────────────────────────────────────────────
    profile_stats = []
    async for profile in profiles.find({"employeeId": employee_id}):
        pid = str(profile["_id"])
        p_pending = await pe_col.count_documents(
            {"profileId": pid, "sendStatus": "pending"}
        )
        p_sent = await pe_col.count_documents(
            {"profileId": pid, "sendStatus": "sent"}
        )
        p_failed = await pe_col.count_documents(
            {"profileId": pid, "sendStatus": "failed"}
        )
        profile_stats.append(
            {
                "profileId": pid,
                "profileName": profile["profileName"],
                "pendingCount": p_pending,
                "sentCount": p_sent,
                "failedCount": p_failed,
            }
        )

    # ── Recent campaigns ─────────────────────────────────────────────────────
    recent_campaigns_cursor = (
        campaigns.find({"employeeId": employee_id})
        .sort("createdAt", -1)
        .limit(10)
    )
    recent_campaigns = serialize_list([d async for d in recent_campaigns_cursor])

    # ── Recent upload logs ───────────────────────────────────────────────────
    recent_uploads_cursor = (
        logs.find({"employeeId": employee_id, "action": "UPLOAD"})
        .sort("createdAt", -1)
        .limit(10)
    )
    recent_uploads = serialize_list([d async for d in recent_uploads_cursor])

    return {
        "todayUploadCount":    today_uploads,
        "last7DaysUploadCount": last_7_uploads,
        "totalUploadCount":    total_uploads,
        "uniqueEmailCount":    unique_emails,
        "activeProfiles":      active_profiles,
        "totalCampaigns":      total_campaigns,
        "runningCampaigns":    running_campaigns,
        "sentToday":           sent_today,
        "sentEmailCount":      sent_total,
        "pendingCount":        pending_total,
        "failedCount":         failed_total,
        "successRate":         success_rate,
        "dailyLimit":          daily_limit,
        "profileStatistics":   profile_stats,
        "recentCampaigns":     recent_campaigns,
        "recentUploadHistory": recent_uploads,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Admin dashboard
# ─────────────────────────────────────────────────────────────────────────────

async def get_admin_dashboard(query: DashboardQuery) -> dict:
    employees  = get_collection("employees")
    master     = get_collection("email_master")
    pe_col     = get_collection("profile_emails")
    campaigns  = get_collection("campaigns")
    profiles   = get_collection("profiles")
    logs       = get_collection("logs")
    accounts   = get_collection("email_accounts")

    start_dt, end_dt = resolve_date_range(query)
    range_match = {"createdAt": {"$gte": start_dt, "$lte": end_dt}}

    # ── Totals ───────────────────────────────────────────────────────────────
    total_employees   = await employees.count_documents({})
    total_uploads     = await master.count_documents(range_match)
    total_unique      = await master.count_documents({**range_match, "isDuplicate": False})
    total_campaigns   = await campaigns.count_documents({})
    running_campaigns = await campaigns.count_documents({"status": "running"})
    total_accounts    = await accounts.count_documents({"isActive": True})

    # Total sent across range
    sent_pipeline = [
        {
            "$match": {
                "action": "CAMPAIGN_COMPLETED",
                "runDate": {"$gte": start_dt, "$lte": end_dt},
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$sentCount"}}},
    ]
    sent_result = await logs.aggregate(sent_pipeline).to_list(length=1)
    total_sent  = sent_result[0]["total"] if sent_result else 0

    # Global pending / failed
    total_pending = await pe_col.count_documents({"sendStatus": "pending"})
    total_failed  = await pe_col.count_documents({"sendStatus": "failed"})

    # ── Employee upload ranking ───────────────────────────────────────────────
    ranking_pipeline = [
        {"$match": range_match},
        {"$group": {"_id": "$employeeId", "uploadedCount": {"$sum": 1}}},
        {"$sort": {"uploadedCount": -1}},
        {"$limit": 20},
    ]
    ranking_rows = await master.aggregate(ranking_pipeline).to_list(length=20)

    sent_by_emp_pipeline = [
        {
            "$match": {
                "action": "CAMPAIGN_COMPLETED",
                "runDate": {"$gte": start_dt, "$lte": end_dt},
            }
        },
        {"$group": {"_id": "$employeeId", "sentCount": {"$sum": "$sentCount"}}},
    ]
    sent_by_emp = {
        row["_id"]: row["sentCount"]
        async for row in logs.aggregate(sent_by_emp_pipeline)
    }

    employee_ranking = []
    for row in ranking_rows:
        emp_id   = row["_id"]
        emp_name = await _employee_name(emp_id)
        employee_ranking.append(
            {
                "employeeId":    emp_id,
                "employeeName":  emp_name,
                "uploadedCount": row["uploadedCount"],
                "sentCount":     sent_by_emp.get(emp_id, 0),
            }
        )

    # ── Last-7-days upload ranking (always fixed window) ─────────────────────
    now          = datetime.now(timezone.utc)
    last_7_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    top7_pipeline = [
        {"$match": {"createdAt": {"$gte": last_7_start}}},
        {"$group": {"_id": "$employeeId", "uploadedCount": {"$sum": 1}}},
        {"$sort": {"uploadedCount": -1}},
        {"$limit": 10},
    ]
    top7_rows = await master.aggregate(top7_pipeline).to_list(length=10)
    top7_ranking = []
    for row in top7_rows:
        emp_name = await _employee_name(row["_id"])
        top7_ranking.append(
            {
                "employeeId":    row["_id"],
                "employeeName":  emp_name,
                "uploadedCount": row["uploadedCount"],
            }
        )

    # ── Campaign performance per employee ─────────────────────────────────────
    campaign_perf_pipeline = [
        {"$match": {"createdAt": {"$gte": start_dt, "$lte": end_dt}}},
        {
            "$group": {
                "_id":           "$employeeId",
                "totalCampaigns": {"$sum": 1},
                "totalSent":     {"$sum": "$sent"},
                "totalFailed":   {"$sum": "$failed"},
            }
        },
        {"$sort": {"totalSent": -1}},
        {"$limit": 20},
    ]
    campaign_perf_rows = await campaigns.aggregate(campaign_perf_pipeline).to_list(length=20)
    campaign_performance = []
    for row in campaign_perf_rows:
        emp_name = await _employee_name(row["_id"])
        campaign_performance.append(
            {
                "employeeId":     row["_id"],
                "employeeName":   emp_name,
                "totalCampaigns": row["totalCampaigns"],
                "totalSent":      row["totalSent"],
                "totalFailed":    row["totalFailed"],
            }
        )

    # ── Profile usage stats ───────────────────────────────────────────────────
    profile_usage_pipeline = [
        {"$group": {"_id": "$employeeId", "profileCount": {"$sum": 1}}},
        {"$sort": {"profileCount": -1}},
        {"$limit": 20},
    ]
    profile_usage = [
        {"employeeId": row["_id"], "profileCount": row["profileCount"]}
        async for row in profiles.aggregate(profile_usage_pipeline)
    ]

    # ── Recent activities (last 20 logs) ─────────────────────────────────────
    recent_activities_cursor = logs.find({}).sort("createdAt", -1).limit(20)
    recent_activities = serialize_list([d async for d in recent_activities_cursor])

    return {
        "totalEmployees":      total_employees,
        "totalUploads":        total_uploads,
        "totalUniqueEmails":   total_unique,
        "totalSentEmails":     total_sent,
        "totalCampaigns":      total_campaigns,
        "runningCampaigns":    running_campaigns,
        "activeEmailAccounts": total_accounts,
        "totalPending":        total_pending,
        "totalFailed":         total_failed,
        "employeeRanking":     employee_ranking,
        "top7DaysUploadRanking": top7_ranking,
        "campaignPerformance": campaign_performance,
        "profileUsage":        profile_usage,
        "recentActivities":    recent_activities,
    }
