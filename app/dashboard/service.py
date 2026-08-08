from datetime import datetime, timedelta, timezone

from app.campaigns.model import CampaignStatus
from app.dashboard.roles import is_admin_dashboard_role, is_super_admin_role
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


def _build_admin_scope(
    admin_user_id: str,
    admin_emp_id: str | None,
    assigned_emp_ids: list[str],
    assigned_user_ids: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    scope_emp_ids: list[str] = []
    if admin_emp_id:
        scope_emp_ids.append(admin_emp_id)

    for emp_id in assigned_emp_ids:
        if emp_id and emp_id not in scope_emp_ids:
            scope_emp_ids.append(emp_id)

    scope_user_ids = [admin_user_id]
    if assigned_user_ids:
        for user_id in assigned_user_ids:
            if user_id and user_id not in scope_user_ids:
                scope_user_ids.append(user_id)

    return scope_emp_ids, scope_user_ids


async def _employee_name(employee_id: str) -> str:
    employees = get_collection("employees")
    emp = await employees.find_one({"_id": _safe_oid(employee_id)})
    if not emp:
        return "Unknown"
    users = get_collection("users")
    user = await users.find_one({"_id": _safe_oid(str(emp["userId"]))})
    return user["name"] if user else "Unknown"


async def _resolve_dashboard_scope(role: str | None, user_id: str | None) -> dict:
    if is_super_admin_role(role):
        return {"is_global": True, "scope_emp_ids": [], "scope_user_ids": []}

    if is_admin_dashboard_role(role):
        employees = get_collection("employees")
        admin_emp = await employees.find_one({"userId": user_id}) if user_id else None
        admin_emp_id = str(admin_emp["_id"]) if admin_emp else None

        if not admin_emp_id:
            return {
                "is_global": False,
                "scope_emp_ids": [],
                "scope_user_ids": [user_id] if user_id else [],
            }

        assigned_employees = await employees.find({"assignedToAdmin": admin_emp_id}).to_list(None)
        assigned_emp_ids = [str(e["_id"]) for e in assigned_employees]
        assigned_user_ids = [str(e["userId"]) for e in assigned_employees if e.get("userId")]

        scope_emp_ids, scope_user_ids = _build_admin_scope(
            admin_user_id=user_id or "",
            admin_emp_id=admin_emp_id,
            assigned_emp_ids=assigned_emp_ids,
            assigned_user_ids=assigned_user_ids,
        )

        return {
            "is_global": False,
            "scope_emp_ids": scope_emp_ids,
            "scope_user_ids": scope_user_ids,
        }

    return {
        "is_global": False,
        "scope_emp_ids": [],
        "scope_user_ids": [user_id] if user_id else [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Employee dashboard
# ─────────────────────────────────────────────────────────────────────────────

async def get_employee_dashboard(employee_id: str, query: DashboardQuery) -> dict:
    master     = get_collection("email_master")
    pe_col     = get_collection("profile_emails")
    campaigns  = get_collection("campaigns")
    profiles   = get_collection("profiles")
    logs       = get_collection("logs")
    employees  = get_collection("employees")
    send_stats = get_collection("daily_send_stats")

    # email_master is global: uploads are owned by users._id in uploadedBy,
    # while the other employee resources use employees._id in employeeId.
    employee = await employees.find_one({"_id": _safe_oid(employee_id)}, {"userId": 1})
    uploader_id = str(employee["userId"]) if employee and employee.get("userId") else employee_id

    now         = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    last_7_start = today_start - timedelta(days=6)
    start_dt, end_dt = resolve_date_range(query)

    # ── Upload counts ────────────────────────────────────────────────────────
    today_uploads  = await master.count_documents(
        {"uploadedBy": uploader_id, "createdAt": {"$gte": today_start}}
    )
    last_7_uploads = await master.count_documents(
        {"uploadedBy": uploader_id, "createdAt": {"$gte": last_7_start}}
    )
    total_uploads  = await master.count_documents(
        {"uploadedBy": uploader_id, "createdAt": {"$gte": start_dt, "$lte": end_dt}}
    )
    unique_emails  = await master.count_documents(
        {
            "uploadedBy": uploader_id,
            "isDuplicate": False,
            "createdAt": {"$gte": start_dt, "$lte": end_dt},
        }
    )
    all_time_uploads = await master.count_documents({"uploadedBy": uploader_id})
    all_time_unique_emails = await master.count_documents({"uploadedBy": uploader_id, "isDuplicate": False})

    # ── Campaign counts ──────────────────────────────────────────────────────
    active_profiles  = await profiles.count_documents(
        {"employeeId": employee_id, "isActive": True}
    )
    # Count unique campaigns (by campaignId/name, not all status instances)
    unique_campaigns_pipeline = [
        {"$match": {"employeeId": employee_id}},
        {"$group": {"_id": "$campaignName"}},
        {"$count": "total"}
    ]
    unique_campaigns_result = await campaigns.aggregate(unique_campaigns_pipeline).to_list(length=1)
    total_campaigns = unique_campaigns_result[0]["total"] if unique_campaigns_result else 0
    
    running_campaigns = await campaigns.count_documents(
        {
            "employeeId": employee_id,
            "status": {"$in": [CampaignStatus.RUNNING.value, CampaignStatus.PROCESSING.value]},
        }
    )

    # ── Aggregate pending across all profiles ──────────────────────────────
    pending_total = await pe_col.count_documents(
        {"employeeId": employee_id, "sendStatus": "pending"}
    )

    # ── Overall Sent (All Time) — immutable daily_send_stats ────────────────────────
    overall_sent_pipeline = [
        {"$match": {"employeeId": employee_id}},
        {"$group": {"_id": None, "total": {"$sum": "$sentCount"}}},
    ]
    overall_sent_res = await send_stats.aggregate(overall_sent_pipeline).to_list(length=1)
    overall_sent = overall_sent_res[0]["total"] if overall_sent_res else 0

    # ── Current Week Sent (Monday–Saturday) — immutable daily_send_stats ───────────
    days_since_monday = now.weekday()
    monday_date_str = (now - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")

    weekly_sent_pipeline = [
        {
            "$match": {
                "employeeId": employee_id,
                "date": {"$gte": monday_date_str},
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$sentCount"}}},
    ]
    weekly_sent_res = await send_stats.aggregate(weekly_sent_pipeline).to_list(length=1)
    current_week_sent = weekly_sent_res[0]["total"] if weekly_sent_res else 0

    return {
        "todayUploadCount":    today_uploads,
        "last7DaysUploadCount": last_7_uploads,
        "totalUploadCount":    total_uploads,
        "uniqueEmailCount":    unique_emails,
        "allTimeUploadCount":  all_time_uploads,
        "allTimeUniqueEmailCount": all_time_unique_emails,
        "activeProfiles":      active_profiles,
        "totalCampaigns":      total_campaigns,
        "runningCampaigns":    running_campaigns,
        "overallSent":         overall_sent,
        "currentWeekSent":     current_week_sent,
        "pendingCount":        pending_total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Admin scoped dashboard (for 'admin' role)
# ─────────────────────────────────────────────────────────────────────────────

async def get_admin_scoped_dashboard(admin_user_id: str, query: DashboardQuery) -> dict:
    """
    Get dashboard data scoped to admin's own uploads + assigned employees only.
    
    Args:
        admin_user_id: The user._id of the admin user
        query: Dashboard query with date range
        
    Returns:
        dict with scoped stats, including adminOwnUploads, assignedEmployeeUploads, etc.
    """
    employees  = get_collection("employees")
    master     = get_collection("email_master")
    pe_col     = get_collection("profile_emails")
    campaigns  = get_collection("campaigns")
    profiles   = get_collection("profiles")
    logs       = get_collection("logs")
    accounts   = get_collection("email_accounts")
    send_stats = get_collection("daily_send_stats")

    start_dt, end_dt = resolve_date_range(query)
    range_match = {"createdAt": {"$gte": start_dt, "$lte": end_dt}}

    # ── Find admin's employee record ──────────────────────────────────────────
    admin_emp = await employees.find_one({"userId": admin_user_id})
    admin_emp_id = str(admin_emp["_id"]) if admin_emp else None
    
    if not admin_emp_id:
        # Admin has no employee record, return empty scoped dashboard
        return {
            "adminOwnUploads": 0,
            "assignedEmployeeUploads": 0,
            "totalUploads": 0,
            "totalDuplicates": 0,
            "totalUniqueEmails": 0,
            "totalSentToProfiles": 0,
            "totalSent": 0,
            "totalCampaigns": 0,
            "runningCampaigns": 0,
            "totalProfiles": 0,
            "activeProfiles": 0,
            
        }

    # ── Find all employees assigned to this admin ─────────────────────────────
    # Note: assignedToAdmin stores the employee._id (ObjectId as string), not user_id
    assigned_employees = await employees.find(
        {"assignedToAdmin": admin_emp_id}
    ).to_list(None)
    assigned_emp_ids = [str(e["_id"]) for e in assigned_employees]
    assigned_user_ids = [str(e["userId"]) for e in assigned_employees if e.get("userId")]

    # Build the scope once so uploads, profiles, campaigns, and sent records all use the same employee/user context.
    scope_emp_ids, scope_user_ids = _build_admin_scope(
        admin_user_id=admin_user_id,
        admin_emp_id=admin_emp_id,
        assigned_emp_ids=assigned_emp_ids,
        assigned_user_ids=assigned_user_ids,
    )
    
    # ── Admin's own upload count (all time) ─────────────────────────────────
    admin_own_uploads = await master.count_documents({"uploadedBy": admin_user_id})
    
    # ── Assigned employees' total upload count (all time) ────────────────────
    assigned_uploads_count = 0
    if assigned_user_ids:
        assigned_uploads_count = await master.count_documents({
            "uploadedBy": {"$in": assigned_user_ids}
        })

    total_uploads = admin_own_uploads + assigned_uploads_count
    
    # ── Duplicates (scoped to these employees) ────────────────────────────────
    duplicates_pipeline = [
        {
            "$match": {
                "action": "UPLOAD",
                "runDate": {"$gte": start_dt, "$lte": end_dt},
                "employeeId": {"$in": scope_emp_ids}
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$duplicateCount"}}}
    ]
    duplicates_result = await logs.aggregate(duplicates_pipeline).to_list(length=1)
    total_duplicates = duplicates_result[0]["total"] if duplicates_result else 0
    
    # ── Unique emails (scoped) ───────────────────────────────────────────────
    # Query email_master by userId (not employeeId)
    total_unique_all_uploads = await master.count_documents({
        "isDuplicate": False,
        "uploadedBy": {"$in": scope_user_ids},
        **range_match
    })
    
    # ── Profiles (scoped to these employees) ──────────────────────────────────
    total_profiles = await profiles.count_documents({
        "employeeId": {"$in": scope_emp_ids}
    })
    
    active_profiles = await profiles.count_documents({
        "employeeId": {"$in": scope_emp_ids},
        "isActive": True
    })
    
    # ── Campaigns (scoped) ───────────────────────────────────────────────────
    unique_campaigns_pipeline = [
        {"$match": {"employeeId": {"$in": scope_emp_ids}}},
        {"$group": {"_id": "$campaignName"}},
        {"$count": "total"}
    ]
    unique_campaigns_result = await campaigns.aggregate(unique_campaigns_pipeline).to_list(length=1)
    total_campaigns = unique_campaigns_result[0]["total"] if unique_campaigns_result else 0
    
    running_campaigns = await campaigns.count_documents({
        "employeeId": {"$in": scope_emp_ids},
        "status": {"$in": [CampaignStatus.RUNNING.value, CampaignStatus.PROCESSING.value]}
    })
    
    # ── Sent to profiles (scoped) ────────────────────────────
    total_sent_profiles = await pe_col.count_documents({
        "employeeId": {"$in": scope_emp_ids},
        "sentDate": {"$gte": start_dt, "$lte": end_dt}
    })
    
    # ── Overall Sent (All Time) — immutable daily_send_stats ────────────────────────
    overall_sent_pipeline = [
        {"$match": {"employeeId": {"$in": scope_emp_ids}}},
        {"$group": {"_id": None, "total": {"$sum": "$sentCount"}}},
    ]
    overall_sent_res = await send_stats.aggregate(overall_sent_pipeline).to_list(length=1)
    overall_sent = overall_sent_res[0]["total"] if overall_sent_res else 0

    # ── Current Week Sent (Monday–Saturday) — immutable daily_send_stats ───────────
    now_admin = datetime.now(timezone.utc)
    monday_date_str = (now_admin - timedelta(days=now_admin.weekday())).strftime("%Y-%m-%d")

    weekly_sent_pipeline = [
        {
            "$match": {
                "employeeId": {"$in": scope_emp_ids},
                "date": {"$gte": monday_date_str},
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$sentCount"}}},
    ]
    weekly_sent_res = await send_stats.aggregate(weekly_sent_pipeline).to_list(length=1)
    current_week_sent = weekly_sent_res[0]["total"] if weekly_sent_res else 0
    
    return {
        "adminOwnUploads": admin_own_uploads,
        "assignedEmployeeUploads": assigned_uploads_count,
        "totalUploads": total_uploads,
        "totalDuplicates": total_duplicates,
        "totalUniqueEmails": total_unique_all_uploads,
        "totalSentToProfiles": total_sent_profiles,
        "overallSent": overall_sent,
        "currentWeekSent": current_week_sent,
        "totalCampaigns": total_campaigns,
        "runningCampaigns": running_campaigns,
        "totalProfiles": total_profiles,
        "activeProfiles": active_profiles,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Admin dashboard (for 'super_admin' role - global view)
# ─────────────────────────────────────────────────────────────────────────────

async def get_admin_dashboard(query: DashboardQuery) -> dict:
    employees  = get_collection("employees")
    master     = get_collection("email_master")
    pe_col     = get_collection("profile_emails")
    campaigns  = get_collection("campaigns")
    profiles   = get_collection("profiles")
    logs       = get_collection("logs")
    accounts   = get_collection("email_accounts")
    send_stats = get_collection("daily_send_stats")

    start_dt, end_dt = resolve_date_range(query)
    range_match = {"createdAt": {"$gte": start_dt, "$lte": end_dt}}

    # ── Global totals for super_admin ───────────────────────────────────────────
    total_employees   = await employees.count_documents({})
    total_uploads     = await master.count_documents({})
    total_unique      = await master.count_documents({"isDuplicate": False})
    
    # Get total duplicates from logs (this is where duplicate count is stored)
    duplicates_pipeline = [
        {"$match": {"action": "UPLOAD"}},
        {"$group": {"_id": None, "total": {"$sum": "$duplicateCount"}}}
    ]
    duplicates_result = await logs.aggregate(duplicates_pipeline).to_list(length=1)
    total_duplicates = duplicates_result[0]["total"] if duplicates_result else 0
    
    # Count unique campaigns (by campaignName, not all status instances)
    unique_campaigns_pipeline = [
        {"$group": {"_id": "$campaignName"}},
        {"$count": "total"}
    ]
    unique_campaigns_result = await campaigns.aggregate(unique_campaigns_pipeline).to_list(length=1)
    total_campaigns = unique_campaigns_result[0]["total"] if unique_campaigns_result else 0
    
    running_campaigns = await campaigns.count_documents({
        "status": {"$in": [CampaignStatus.RUNNING.value, CampaignStatus.PROCESSING.value]}
    })
    total_accounts    = await accounts.count_documents({"isActive": True})
    total_profiles    = await profiles.count_documents({})  # Count all profiles

    # Total sent to profiles (count of profile_emails records)
    total_sent_profiles = await pe_col.count_documents({})
    
    # ── Overall Sent (All Time) — immutable daily_send_stats ────────────────────────
    overall_sent_pipeline = [
        {"$match": {}},
        {"$group": {"_id": None, "total": {"$sum": "$sentCount"}}},
    ]
    overall_sent_res = await send_stats.aggregate(overall_sent_pipeline).to_list(length=1)
    overall_sent = overall_sent_res[0]["total"] if overall_sent_res else 0

    # ── Current Week Sent (Monday–Saturday) — immutable daily_send_stats ───────────
    now = datetime.now(timezone.utc)
    monday_date_str = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

    weekly_sent_pipeline = [
        {
            "$match": {
                "date": {"$gte": monday_date_str},
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$sentCount"}}},
    ]
    weekly_sent_res = await send_stats.aggregate(weekly_sent_pipeline).to_list(length=1)
    current_week_sent = weekly_sent_res[0]["total"] if weekly_sent_res else 0

    # Active profiles
    active_profiles = await profiles.count_documents({"isActive": True})

    # ── Employee upload ranking ───────────────────────────────────────────────
    ranking_pipeline = [
        {"$group": {"_id": "$employeeId", "uploadedCount": {"$sum": 1}}},
        {"$sort": {"uploadedCount": -1}},
        {"$limit": 20},
    ]
    ranking_rows = await master.aggregate(ranking_pipeline).to_list(length=20)

    sent_by_emp_pipeline = [
        {
            "$match": {
                "action": "CAMPAIGN_COMPLETED",
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
            }
        )

    # ── Detailed employee performance ──────────────────────────────────────────
    employee_performance = []
    
    # Pre-fetch users for name mapping to avoid N+1 query overhead
    users_col = get_collection("users")
    user_map = {str(u["_id"]): u.get("name", "Unknown") async for u in users_col.find()}
    
    async for emp in employees.find():
        emp_id = str(emp["_id"])
        user_id = str(emp.get("userId", "")) if emp.get("userId") else None
        emp_name = user_map.get(user_id, "Unknown") if user_id else "Unknown"
        
        # Get uploads (count by userId who uploaded)
        total_emp_uploads = await master.count_documents({
            "uploadedBy": user_id
        }) if user_id else 0
        
        # Get duplicate count from logs for this employee (by userId)
        emp_duplicates_pipeline = [
            {
                "$match": {
                    "employeeId": emp_id,
                    "action": "UPLOAD",
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$duplicateCount"}}}
        ]
        emp_duplicates_result = await logs.aggregate(emp_duplicates_pipeline).to_list(length=1)
        emp_duplicates = emp_duplicates_result[0]["total"] if emp_duplicates_result else 0
        
        # Get sent to profiles (total records added to profile_emails from email_master)
        emp_sent_profiles = await pe_col.count_documents({
            "employeeId": emp_id,
        })
        
        # Get actually sent (sendStatus: sent)
        emp_sent = await pe_col.count_documents({
            "employeeId": emp_id,
            "sendStatus": "sent",
        })
        
        # Get employee's profiles count (using employeeId)
        emp_total_profiles = await profiles.count_documents({
            "employeeId": emp_id
        })
        
        # Get employee's total campaigns (unique campaigns by campaignName, using employeeId)
        emp_total_campaigns_pipeline = [
            {"$match": {"employeeId": emp_id}},
            {"$group": {"_id": "$campaignName"}},
            {"$count": "total"}
        ]
        emp_total_campaigns_result = await campaigns.aggregate(emp_total_campaigns_pipeline).to_list(length=1)
        emp_total_campaigns = emp_total_campaigns_result[0]["total"] if emp_total_campaigns_result else 0
        
        # Get employee's running campaigns (status: "running", using employeeId)
        emp_running_campaigns = await campaigns.count_documents({
            "employeeId": emp_id,
            "status": {"$in": [CampaignStatus.RUNNING.value, CampaignStatus.PROCESSING.value]}
        })
        
        employee_performance.append({
            "employeeId": emp_id,
            "employeeName": emp_name,
            "totalUploads": total_emp_uploads,
            "totalDuplicates": emp_duplicates,
            "totalSentToProfiles": emp_sent_profiles,
            "totalSent": emp_sent,
            "totalProfiles": emp_total_profiles,
            "totalCampaigns": emp_total_campaigns,
            "runningCampaigns": emp_running_campaigns,
            "successRate": round((emp_sent / emp_sent_profiles * 100), 1) if emp_sent_profiles > 0 else 0
        })

    return {
        "totalEmployees":      total_employees,
        "totalUploads":        total_uploads,
        "totalDuplicates":     total_duplicates,
        "totalUniqueEmails":   total_unique,
        "totalSentToProfiles": total_sent_profiles,
        "overallSent":         overall_sent,
        "currentWeekSent":     current_week_sent,
        "totalCampaigns":      total_campaigns,
        "runningCampaigns":    running_campaigns,
        "activeEmailAccounts": total_accounts,
        "totalProfiles":       total_profiles,
        "activeProfiles":      active_profiles,
        # Overall metrics (not date-filtered)
        "overallEmailMaster":  await master.count_documents({}),
        "overallProfileEmails": await pe_col.count_documents({}),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dropdown Options
# ─────────────────────────────────────────────────────────────────────────────

async def get_dropdown_options(current_user=None) -> dict:
    """Get dropdown options scoped to the current admin or the full system for super admins."""
    employees_col = get_collection("employees")
    users_col = get_collection("users")
    profiles_col = get_collection("profiles")
    campaigns_col = get_collection("campaigns")

    role = getattr(current_user, "role", None)
    user_id = getattr(current_user, "user_id", None)
    scope = await _resolve_dashboard_scope(role, user_id)
    is_global = scope["is_global"]
    scope_emp_ids = set(scope["scope_emp_ids"])
    scope_user_ids = set(scope["scope_user_ids"])

    # Get employees with names
    employees = []
    async for emp in employees_col.find():
        emp_id = str(emp["_id"])
        if not is_global and emp_id not in scope_emp_ids:
            continue

        user = await users_col.find_one({"_id": _safe_oid(emp["userId"])})
        emp_name = user.get("name", "Unknown") if user else "Unknown"
        employees.append({
            "id": emp_id,
            "name": emp_name,
            "email": user.get("email", "") if user else ""
        })

    # Get admins (users with role=admin)
    admins = []
    if is_global:
        async for user in users_col.find({"role": "admin"}):
            user_id_value = str(user["_id"])
            admins.append({
                "id": user_id_value,
                "name": user.get("name", "Unknown"),
                "email": user.get("email", "")
            })
    elif user_id:
        user_doc = await users_col.find_one({"_id": _safe_oid(user_id)})
        if user_doc:
            admins.append({
                "id": str(user_doc["_id"]),
                "name": user_doc.get("name", "Unknown"),
                "email": user_doc.get("email", "")
            })

    # Get profiles with employee names
    profiles = []
    async for profile in profiles_col.find():
        profile_id = str(profile["_id"])
        emp_id = profile.get("employeeId")
        emp_id_str = str(emp_id) if emp_id is not None else None
        if not is_global and emp_id_str not in scope_emp_ids:
            continue

        emp = await employees_col.find_one({"_id": _safe_oid(emp_id)})
        emp_user = await users_col.find_one({"_id": _safe_oid(emp.get("userId"))}) if emp else None
        emp_name = emp_user.get("name", "Unknown") if emp_user else "Unknown"

        profiles.append({
            "id": profile_id,
            "name": profile.get("profileName", "Unnamed"),
            "employeeId": emp_id,
            "employeeName": emp_name,
            "email": profile.get("gmailAccount", "")
        })

    # Get campaigns with names and details
    campaigns = []
    async for campaign in campaigns_col.find():
        campaign_id = str(campaign["_id"])
        emp_id = campaign.get("employeeId")
        emp_id_str = str(emp_id) if emp_id is not None else None
        if not is_global and emp_id_str not in scope_emp_ids:
            continue

        emp = await employees_col.find_one({"_id": _safe_oid(emp_id)})
        emp_user = await users_col.find_one({"_id": _safe_oid(emp.get("userId"))}) if emp else None
        emp_name = emp_user.get("name", "Unknown") if emp_user else "Unknown"

        campaigns.append({
            "id": campaign_id,
            "name": campaign.get("campaignName", "Unnamed"),
            "status": campaign.get("status", "pending"),
            "employeeId": emp_id,
            "employeeName": emp_name,
            "profileId": campaign.get("profileId", ""),
            "sent": campaign.get("sent", 0),
            "totalEmails": campaign.get("totalEmails", 0)
        })

    return {
        "employees": employees,
        "admins": admins,
        "profiles": profiles,
        "campaigns": campaigns
    }


# ─────────────────────────────────────────────────────────────────────────────
# Upload History
# ─────────────────────────────────────────────────────────────────────────────

async def get_upload_history(
    query: DashboardQuery,
    employee_id: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user=None,
) -> dict:
    """Fetch paginated upload history from logs, grouped by employee per day."""
    logs = get_collection("logs")
    users_col = get_collection("users")
    employees_col = get_collection("employees")

    role = getattr(current_user, "role", None)
    user_id = getattr(current_user, "user_id", None)
    scope = await _resolve_dashboard_scope(role, user_id)
    is_global = scope["is_global"]
    scope_user_ids = set(scope["scope_user_ids"])
    scope_emp_ids = set(scope["scope_emp_ids"])

    start_dt, end_dt = resolve_date_range(query)

    # Build map: userId -> {name, email} for active users
    active_users: dict[str, dict] = {}
    async for u in users_col.find():
        active_users[str(u["_id"])] = {
            "name": u.get("name", "Unknown"),
            "email": u.get("email", "N/A"),
        }

    # Build map: employeeId -> userId  (employees collection links them)
    emp_to_user: dict[str, str] = {}
    async for emp in employees_col.find({}, {"_id": 1, "userId": 1}):
        emp_to_user[str(emp["_id"])] = str(emp.get("userId", ""))

    # Resolve the requested employeeId filter to a userId for matching
    filter_user_id: str | None = None
    if employee_id:
        filter_user_id = emp_to_user.get(employee_id)

    match_stage: dict = {
        "action": "UPLOAD",
        "runDate": {"$gte": start_dt, "$lte": end_dt},
    }
    pipeline = [{"$match": match_stage}, {"$sort": {"runDate": -1}}]

    # ── First pass: collect all raw log records
    raw_records: list[dict] = []
    employee_set: dict[str, dict] = {}  # employeeId -> {id, name, email}

    async for log in logs.aggregate(pipeline):
        emp_id = log.get("employeeId")

        # emp_id here is the userId stored in logs (not employees._id)
        if emp_id not in active_users:
            continue

        if not is_global and emp_id not in scope_user_ids:
            continue

        user_info = active_users[emp_id]
        resolved_emp_id = emp_id  # fallback — use userId if no employee doc exists

        # Track unique employees for the dropdown
        if resolved_emp_id not in employee_set:
            employee_set[resolved_emp_id] = {
                "id": resolved_emp_id,
                "name": user_info["name"],
                "email": user_info["email"],
            }

        up  = log.get("uploadedCount", 0)
        uq  = log.get("uniqueCount", 0)
        dp  = log.get("duplicateCount", 0)
        inv = max(0, up - uq - dp)

        # Extract the calendar date (YYYY-MM-DD) for grouping — multiple uploads
        # on the same day will be collapsed into a single row per employee.
        run_date: datetime = log.get("runDate")
        date_key = run_date.strftime("%Y-%m-%d") if run_date else "unknown"

        raw_records.append({
            "employeeId":    resolved_emp_id,
            "employeeName":  user_info["name"],
            "employeeEmail": user_info["email"],
            "uploadCount":   up,
            "uniqueCount":   uq,
            "duplicateCount": dp,
            "invalidCount":  inv,
            "date_key":      date_key,   # for grouping (not sent to client)
            "date":          date_key,   # date-only string (YYYY-MM-DD), no time
        })

    # ── Apply employee filter
    if employee_id:
        if not is_global and employee_id not in scope_emp_ids and employee_id not in scope_user_ids and filter_user_id not in scope_user_ids:
            raw_records = []
        else:
            raw_records = [
                r for r in raw_records
                if r["employeeId"] == employee_id or r["employeeId"] == filter_user_id
            ]

    # ── Group by (employeeId, date_key) → one row per employee per calendar day
    grouped: dict[tuple, dict] = {}

    for r in raw_records:
        key = (r["employeeId"], r["date_key"])
        if key not in grouped:
            grouped[key] = {
                "employeeId":    r["employeeId"],
                "employeeName":  r["employeeName"],
                "employeeEmail": r["employeeEmail"],
                "uploadCount":   0,
                "uniqueCount":   0,
                "duplicateCount": 0,
                "invalidCount":  0,
                "date":          r["date"],
                "date_key":      r["date_key"],
            }
        g = grouped[key]
        g["uploadCount"]    += r["uploadCount"]
        g["uniqueCount"]    += r["uniqueCount"]
        g["duplicateCount"] += r["duplicateCount"]
        g["invalidCount"]   += r["invalidCount"]
        # date is already a date-only string (YYYY-MM-DD); no timestamp comparison needed

    # Sort: latest date first, then employee name
    filtered = sorted(
        grouped.values(),
        key=lambda x: (x["date_key"], x["employeeName"]),
        reverse=True,
    )

    # ── Compute totals on the full filtered set
    total_uploads   = sum(r["uploadCount"]    for r in filtered)
    total_unique    = sum(r["uniqueCount"]    for r in filtered)
    total_duplicate = sum(r["duplicateCount"] for r in filtered)
    total_invalid   = sum(r["invalidCount"]   for r in filtered)

    # ── Paginate
    total_records = len(filtered)
    total_pages   = max(1, (total_records + page_size - 1) // page_size)
    skip          = (page - 1) * page_size
    paginated     = filtered[skip: skip + page_size]

    # Remove internal helper field before sending to client
    for rec in paginated:
        rec.pop("date_key", None)

    # ── Build employee dropdown list sorted by name
    employees_dropdown = sorted(employee_set.values(), key=lambda e: e["name"])

    # ── Today's work status (per-employee, always fixed to today regardless of date filter)
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    pe_col = get_collection("profile_emails")
    campaigns_col = get_collection("campaigns")

    all_user_ids = list(employee_set.keys())

    # Today's upload stats from logs (grouped by employeeId = userId)
    today_upload_agg = await logs.aggregate([
        {
            "$match": {
                "action": "UPLOAD",
                "runDate": {"$gte": today_start},
                "employeeId": {"$in": all_user_ids},
            }
        },
        {
            "$group": {
                "_id": "$employeeId",
                "uploadCount":    {"$sum": "$uploadedCount"},
                "uniqueCount":    {"$sum": "$uniqueCount"},
                "duplicateCount": {"$sum": "$duplicateCount"},
                "uploadEvents":   {"$sum": 1},
            }
        }
    ]).to_list(None)
    today_upload_map = {r["_id"]: r for r in today_upload_agg}

    # Build reverse map: userId -> employees._id
    user_to_emp: dict[str, str] = {v: k for k, v in emp_to_user.items()}
    emp_ids_for_today = [user_to_emp[uid] for uid in all_user_ids if uid in user_to_emp]

    # Today's sent emails from profile_emails
    today_sent_agg = await pe_col.aggregate([
        {
            "$match": {
                "sendStatus": "sent",
                "sentDate": {"$gte": today_start},
                "employeeId": {"$in": emp_ids_for_today},
            }
        },
        {"$group": {"_id": "$employeeId", "sentCount": {"$sum": 1}}},
    ]).to_list(None)
    today_sent_map = {r["_id"]: r["sentCount"] for r in today_sent_agg}

    # Running campaigns (not date-filtered — current live status)
    running_agg = await campaigns_col.aggregate([
        {
            "$match": {
                "employeeId": {"$in": emp_ids_for_today},
                "status": {"$in": ["running", "processing"]},
            }
        },
        {"$group": {"_id": "$employeeId", "count": {"$sum": 1}}},
    ]).to_list(None)
    running_map = {r["_id"]: r["count"] for r in running_agg}

    # Assemble todayStatus list (all active employees, even those with 0 activity)
    today_status = []
    for uid, emp_info in employee_set.items():
        up_stats = today_upload_map.get(uid, {})
        up       = up_stats.get("uploadCount", 0)
        uq       = up_stats.get("uniqueCount", 0)
        dp       = up_stats.get("duplicateCount", 0)
        inv      = max(0, up - uq - dp)
        eid      = user_to_emp.get(uid, uid)   # employees._id (fallback to userId)

        today_status.append({
            "employeeId":      uid,
            "employeeName":    emp_info["name"],
            "employeeEmail":   emp_info["email"],
            "uploadCount":     up,
            "uniqueCount":     uq,
            "duplicateCount":  dp,
            "invalidCount":    inv,
            "uploadEvents":    up_stats.get("uploadEvents", 0),
            "runningCampaigns": running_map.get(eid, 0),
        })

    # Sort by upload count desc
    today_status.sort(key=lambda x: x["uploadCount"], reverse=True)

    return {
        "records": paginated,
        "employees": employees_dropdown,
        "totals": {
            "totalUploads": total_uploads,
            "totalUnique": total_unique,
            "totalDuplicate": total_duplicate,
            "totalInvalid": total_invalid,
        },
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total_records,
            "total_pages": total_pages,
        },
        "todayStatus": today_status,
    }

