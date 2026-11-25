from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.campaigns.time_format import format_campaign_time_12_hour
from app.dashboard.service import _get_current_month_range, _get_last_month_range
from app.database.mongodb import get_collection
from app.users.unknown import UNKNOWN_MARKER, UNKNOWN_USER_ID

METRICS = ("mail", "convert", "both")
MAILS_PER_POINT = 100
CONVERSION_POINTS = 5


def _period_bounds(now: datetime, previous: bool) -> tuple[datetime, datetime]:
    if previous:
        start, end_date = _get_last_month_range(now)
    else:
        start, end_date = _get_current_month_range(now)
    return start, end_date + timedelta(days=1)


def _period_response(
    start: datetime,
    end_exclusive: datetime,
    now: datetime,
) -> dict:
    end_date = (end_exclusive - timedelta(days=1)).date()
    start_date = start.date()
    return {
        "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(),
        "startDateDisplay": format_campaign_time_12_hour(
            f"{start_date.isoformat()}T00:00"
        ),
        "endDateDisplay": format_campaign_time_12_hour(
            f"{end_date.isoformat()}T00:00"
        ),
        "finalized": end_exclusive <= now,
    }


def _leaderboard_rows(
    users: dict[str, dict[str, Any]],
    mail_counts: dict[str, int],
    convert_counts: dict[str, int],
    metric: str,
) -> list[dict]:
    rows = []
    for user_id, user in users.items():
        mail_count = mail_counts.get(user_id, 0)
        convert_count = convert_counts.get(user_id, 0)
        mail_score = round(mail_count / MAILS_PER_POINT, 2)
        convert_score = convert_count * CONVERSION_POINTS
        score = (
            mail_score
            if metric == "mail"
            else convert_score
            if metric == "convert"
            else round(mail_score + convert_score, 2)
        )
        if score <= 0:
            continue
        rows.append(
            {
                "employeeId": user_id,
                "employeeName": user["name"],
                "role": user.get("role"),
                "profilePictureUrl": user.get("profilePictureUrl"),
                "branch": user.get("branch"),
                "mailCount": mail_count,
                "convertCount": convert_count,
                "score": score,
            }
        )
    rows.sort(
        key=lambda row: (
            -row["score"],
            row["employeeName"].casefold(),
            row["employeeId"],
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank
    return rows


async def _load_leaderboard_users() -> dict[str, dict[str, Any]]:
    users_collection = get_collection("users")
    employees_collection = get_collection("employees")
    from app.users.service import _profile_picture_url

    unknown_user_object_id = ObjectId(UNKNOWN_USER_ID)
    employee_branches = {
        str(employee.get("userId")): employee.get("branch")
        async for employee in employees_collection.find(
            {}, {"userId": 1, "branch": 1}
        )
        if employee.get("userId")
    }

    users: dict[str, dict[str, Any]] = {}
    async for user in users_collection.find(
        {
            "role": {"$in": ["employee", "admin", "super_admin"]},
            "_id": {"$ne": unknown_user_object_id},
            "systemAccount": {"$ne": UNKNOWN_MARKER},
        }
    ):
        if (
            str(user["_id"]) == UNKNOWN_USER_ID
            or user.get("systemAccount") == UNKNOWN_MARKER
        ):
            continue
        user_id = str(user["_id"])
        users[user_id] = {
            "name": user.get("name") or user.get("email") or "Unknown",
            "role": user.get("role"),
            "profilePictureUrl": (
                _profile_picture_url(user_id)
                if ObjectId.is_valid(user_id)
                else None
            ),
            "branch": user.get("branch") or employee_branches.get(user_id),
        }
    return users


def _exclude_unknown_users(
    users: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        user_id: user
        for user_id, user in users.items()
        if user_id != UNKNOWN_USER_ID
        and user.get("systemAccount") != UNKNOWN_MARKER
    }


def _database_user_ids(user_ids: list[str]) -> list[Any]:
    values: list[Any] = list(user_ids)
    values.extend(ObjectId(user_id) for user_id in user_ids if ObjectId.is_valid(user_id))
    return values


async def _aggregate_counts(
    collection_name: str,
    match: dict,
    group_field: str,
) -> dict[str, int]:
    rows = await get_collection(collection_name).aggregate(
        [
            {"$match": match},
            {"$group": {"_id": f"${group_field}", "count": {"$sum": 1}}},
        ]
    ).to_list(length=None)
    return {
        str(row["_id"]): int(row["count"])
        for row in rows
        if row.get("_id") is not None
    }


async def _get_period_counts(
    start: datetime,
    end_exclusive: datetime,
    user_ids: list[str],
) -> tuple[dict[str, int], dict[str, int]]:
    if not user_ids:
        return {}, {}

    stored_ids = _database_user_ids(user_ids)
    upload_counts = await _aggregate_counts(
        "email_master",
        {
            "uploadedBy": {"$in": stored_ids},
            "$or": [
                {"uploadedDate": {"$gte": start, "$lt": end_exclusive}},
                {
                    "uploadedDate": {"$exists": False},
                    "createdAt": {"$gte": start, "$lt": end_exclusive},
                },
            ],
        },
        "uploadedBy",
    )
    convert_counts = await _aggregate_counts(
        "email_master",
        {
            "replyReason": "converted",
            "replyMarkedBy": {"$in": stored_ids},
            "replyMarkedAt": {"$gte": start, "$lt": end_exclusive},
        },
        "replyMarkedBy",
    )
    return upload_counts, convert_counts


def _build_period_boards(
    users: dict[str, dict[str, Any]],
    mail_counts: dict[str, int],
    convert_counts: dict[str, int],
) -> list[dict]:
    scopes: list[tuple[str, str | None, dict[str, dict[str, Any]]]] = [
        ("global", None, users)
    ]
    branch_names: dict[str, str] = {}
    for user in users.values():
        branch = str(user.get("branch") or "").strip()
        if branch:
            branch_names.setdefault(branch.casefold(), branch)

    for normalized_branch, branch in sorted(branch_names.items()):
        branch_users = {
            user_id: user
            for user_id, user in users.items()
            if str(user.get("branch") or "").strip().casefold() == normalized_branch
        }
        scopes.append(("branch", branch, branch_users))

    boards = []
    for scope, branch, scoped_users in scopes:
        for metric in METRICS:
            rows = _leaderboard_rows(
                scoped_users, mail_counts, convert_counts, metric
            )
            boards.append(
                {
                    "scope": scope,
                    "branch": branch,
                    "branchKey": (branch or "").strip().casefold(),
                    "metric": metric,
                    "leaderboard": rows,
                    "top3": rows[:3],
                }
            )
    return boards


async def archive_previous_achievement_period(
    now: datetime | None = None,
) -> dict:
    """Persist the closed 26th-to-25th period and its monthly top-three awards."""
    now = now or datetime.now(timezone.utc)
    start, end_exclusive = _period_bounds(now, previous=True)
    period_key = start.date().isoformat()
    periods = get_collection("achievement_periods")
    existing_period = await periods.find_one(
        {"periodKey": period_key, "finalized": True},
        {"_id": 1},
    )
    if existing_period:
        return {"periodKey": period_key, "alreadyArchived": True}

    users = _exclude_unknown_users(await _load_leaderboard_users())
    mail_counts, convert_counts = await _get_period_counts(
        start, end_exclusive, list(users)
    )
    boards = _build_period_boards(users, mail_counts, convert_counts)
    awards = get_collection("achievement_awards")

    for board in boards:
        for entry in board["top3"]:
            award_query = {
                "periodKey": period_key,
                "scope": board["scope"],
                "branchKey": board["branchKey"],
                "metric": board["metric"],
                "employeeId": entry["employeeId"],
            }
            previous_count = await awards.count_documents(
                {
                    "scope": board["scope"],
                    "branchKey": board["branchKey"],
                    "metric": board["metric"],
                    "employeeId": entry["employeeId"],
                }
            )
            existing_award = await awards.find_one(
                award_query,
                {"timesAchieved": 1},
            )
            award = {
                **award_query,
                "branch": board["branch"],
                "employeeName": entry["employeeName"],
                "role": entry.get("role"),
                "rank": entry["rank"],
                "score": entry["score"],
                "mailCount": entry["mailCount"],
                "convertCount": entry["convertCount"],
                "timesAchieved": (
                    existing_award.get("timesAchieved")
                    if existing_award
                    else previous_count + 1
                ),
                "periodStart": start,
                "periodEnd": end_exclusive - timedelta(days=1),
                "createdAt": now,
            }
            entry["timesAchieved"] = award["timesAchieved"]
            try:
                await awards.update_one(
                    award_query,
                    {"$setOnInsert": award},
                    upsert=True,
                )
            except DuplicateKeyError:
                # Another scheduler worker archived this same award concurrently.
                continue

    period = {
        "periodKey": period_key,
        "periodStart": start,
        "periodEnd": end_exclusive - timedelta(days=1),
        "finalized": True,
        "leaderboards": boards,
        "updatedAt": now,
    }
    await periods.update_one(
        {"periodKey": period_key},
        {"$set": period, "$setOnInsert": {"createdAt": now}},
        upsert=True,
    )
    return {"periodKey": period_key, "alreadyArchived": False}


async def _add_award_counts(
    rows: list[dict],
    scope: str,
    branch_key: str,
    metric: str,
) -> list[dict]:
    awards = get_collection("achievement_awards")
    result = []
    for row in rows:
        times_achieved = await awards.count_documents(
            {
                "scope": scope,
                "branchKey": branch_key,
                "metric": metric,
                "employeeId": row["employeeId"],
            }
        )
        result.append({**row, "timesAchieved": times_achieved})
    return result


async def get_leaderboard(
    metric: str,
    scope: str,
    branch: str | None,
    permitted_user_ids: set[str] | None = None,
    now: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    current_start, current_end_exclusive = _period_bounds(now, previous=False)
    previous_start, previous_end_exclusive = _period_bounds(now, previous=True)
    if (start_date is None) != (end_date is None):
        raise ValueError("start_date and end_date must be provided together")
    if start_date and end_date and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    # The scheduler archives daily; archive here too so the previous month's
    # winners are available immediately after a deployment or missed scheduler run.
    await archive_previous_achievement_period(now)

    users = _exclude_unknown_users(await _load_leaderboard_users())
    if scope == "branch":
        branch_key = (branch or "").strip().casefold()
        users = {
            user_id: user
            for user_id, user in users.items()
            if str(user.get("branch") or "").strip().casefold() == branch_key
        }
    else:
        branch_key = ""
    if permitted_user_ids is not None:
        users = {
            user_id: user for user_id, user in users.items()
            if user_id in permitted_user_ids
        }

    monthly_mail_counts, monthly_convert_counts = await _get_period_counts(
        current_start, current_end_exclusive, list(users)
    )
    current_rows = _leaderboard_rows(
        users, monthly_mail_counts, monthly_convert_counts, metric
    )
    if start_date and end_date:
        live_start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        live_end_exclusive = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        live_mail_counts, live_convert_counts = await _get_period_counts(
            live_start, live_end_exclusive, list(users)
        )
        live_rows = _leaderboard_rows(
            users, live_mail_counts, live_convert_counts, metric
        )
        live_period = _period_response(live_start, live_end_exclusive, now)
        current_rows = await _add_award_counts(
            current_rows, scope, branch_key, metric
        )
        live_rows = await _add_award_counts(
            live_rows, scope, branch_key, metric
        )
    else:
        live_rows = await _add_award_counts(
            current_rows, scope, branch_key, metric
        )
        current_rows = live_rows
        live_period = _period_response(current_start, current_end_exclusive, now)

    period_key = previous_start.date().isoformat()
    previous_doc = await get_collection("achievement_periods").find_one(
        {"periodKey": period_key, "finalized": True},
        {"leaderboards": 1},
    )
    previous_board = None
    if previous_doc:
        previous_board = next(
            (
                board
                for board in previous_doc.get("leaderboards", [])
                if board.get("scope") == scope
                and board.get("branchKey", "") == branch_key
                and board.get("metric") == metric
            ),
            None,
        )
    previous_rows = (previous_board or {}).get(
        "leaderboard",
        (previous_board or {}).get("top3", []),
    )
    previous_rows = [
        row
        for row in previous_rows
        if str(row.get("employeeId")) != UNKNOWN_USER_ID
    ]
    if permitted_user_ids is not None:
        previous_rows = [
            row for row in previous_rows
            if row["employeeId"] in permitted_user_ids
        ]
    if scope == "branch":
        previous_rows = [
            row
            for row in previous_rows
            if str(row.get("branch") or "").strip().casefold() == branch_key
        ]
    previous_rows = [
        {
            **row,
            "rank": rank,
            "profilePictureUrl": users.get(row["employeeId"], {}).get(
                "profilePictureUrl"
            ),
        }
        for rank, row in enumerate(previous_rows, start=1)
    ]
    previous_rows = await _add_award_counts(
        previous_rows,
        scope,
        branch_key,
        metric,
    )
    previous_top3 = previous_rows[:3]
    return {
        "scope": scope,
        "branch": branch if scope == "branch" else None,
        "metric": metric,
        "currentPeriod": _period_response(
            current_start, current_end_exclusive, now
        ),
        "livePeriod": live_period,
        "previousPeriod": _period_response(
            previous_start, previous_end_exclusive, now
        ),
        "liveLeaderboard": live_rows,
        "currentTop3": current_rows[:3],
        "previousTop3": previous_top3,
    }
