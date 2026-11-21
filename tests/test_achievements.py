from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from bson import ObjectId

from app.achievements import service
from app.achievements.router import get_achievements_leaderboard
from app.core.dependencies import CurrentUser
from app.core.exceptions import BadRequestException
from app.users.unknown import UNKNOWN_MARKER, UNKNOWN_USER_ID


class AsyncDocuments:
    def __init__(self, documents):
        self.documents = iter(documents)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.documents)
        except StopIteration:
            raise StopAsyncIteration


class AggregateCursor:
    def __init__(self, documents):
        self.documents = documents

    async def to_list(self, length=None):
        return self.documents[:length] if length is not None else self.documents


def test_office_periods_match_dashboard_26th_to_25th_boundaries():
    now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)

    current_start, current_end = service._period_bounds(now, previous=False)
    previous_start, previous_end = service._period_bounds(now, previous=True)

    assert current_start == datetime(2026, 10, 26, tzinfo=timezone.utc)
    assert current_end == datetime(2026, 11, 26, tzinfo=timezone.utc)
    assert previous_start == datetime(2026, 9, 26, tzinfo=timezone.utc)
    assert previous_end == datetime(2026, 10, 26, tzinfo=timezone.utc)


def test_combined_leaderboard_weights_uploads_and_conversions():
    users = {
        "u1": {"name": "Alex", "branch": "North"},
        "u2": {"name": "Bea", "branch": "North"},
        "u3": {"name": "Casey", "branch": "South"},
    }

    rows = service._leaderboard_rows(
        users,
        {"u1": 5, "u2": 4, "u3": 3},
        {"u1": 2, "u2": 3, "u3": 4},
        "both",
    )

    assert [(row["employeeId"], row["score"], row["rank"]) for row in rows] == [
        ("u3", 20.03, 1),
        ("u2", 15.04, 2),
        ("u1", 10.05, 3),
    ]


def test_leaderboard_points_weight_mail_and_conversions():
    users = {
        "u70": {"name": "Seventy"},
        "u100": {"name": "Hundred"},
        "uconvert": {"name": "Converter"},
    }
    mail_counts = {"u70": 70, "u100": 100}
    convert_counts = {"u100": 1, "uconvert": 1}

    mail_rows = service._leaderboard_rows(
        users, mail_counts, convert_counts, "mail"
    )
    convert_rows = service._leaderboard_rows(
        users, mail_counts, convert_counts, "convert"
    )
    combined_rows = service._leaderboard_rows(
        users, mail_counts, convert_counts, "both"
    )

    assert [(row["employeeId"], row["score"]) for row in mail_rows] == [
        ("u100", 1),
        ("u70", 0.7),
    ]
    assert [(row["employeeId"], row["score"]) for row in convert_rows] == [
        ("uconvert", 5),
        ("u100", 5),
    ]
    assert [(row["employeeId"], row["score"]) for row in combined_rows] == [
        ("u100", 6),
        ("uconvert", 5),
        ("u70", 0.7),
    ]


@pytest.mark.anyio
async def test_archives_top_three_and_tracks_times_achieved_idempotently():
    users = [
        {"_id": "u1", "name": "Alex", "role": "employee", "branch": "North"},
        {"_id": "u2", "name": "Bea", "role": "employee", "branch": "North"},
        {"_id": "u3", "name": "Casey", "role": "employee", "branch": "South"},
        {"_id": "u4", "name": "Dev", "role": "employee", "branch": "South"},
        {"_id": "u5", "name": "Admin", "role": "admin", "branch": "North"},
        {"_id": "u6", "name": "Super Admin", "role": "super_admin", "branch": "South"},
    ]
    mail_counts = {"u1": 10, "u2": 9, "u3": 8, "u4": 1, "u5": 11, "u6": 12}
    convert_counts = {"u1": 0, "u2": 3, "u3": 3, "u4": 4}
    awards_by_key = {}
    stored_period = None

    class FakeUsers:
        def find(self, _query):
            return AsyncDocuments(users)

    class FakeEmployees:
        def find(self, _query, _projection):
            return AsyncDocuments(
                [{"userId": user["_id"], "branch": user["branch"]} for user in users]
            )

    class FakeEmailMaster:
        def aggregate(self, pipeline):
            group_field = pipeline[1]["$group"]["_id"].removeprefix("$")
            counts = mail_counts if group_field == "uploadedBy" else convert_counts
            return AggregateCursor(
                [{"_id": user_id, "count": count} for user_id, count in counts.items()]
            )

    class FakeAwards:
        async def count_documents(self, query):
            return sum(
                all(award.get(key) == value for key, value in query.items())
                for award in awards_by_key.values()
            )

        async def find_one(self, query, _projection):
            key = tuple(query.values())
            return awards_by_key.get(key)

        async def update_one(self, query, update, upsert):
            assert upsert is True
            key = tuple(query.values())
            awards_by_key.setdefault(key, update["$setOnInsert"])

    class FakePeriods:
        async def find_one(self, query, _projection):
            if (
                stored_period
                and stored_period["periodKey"] == query["periodKey"]
                and stored_period["finalized"] is True
            ):
                return {"_id": "period"}
            return None

        async def update_one(self, query, update, upsert):
            nonlocal stored_period
            assert upsert is True
            stored_period = {
                **update["$setOnInsert"],
                **update["$set"],
                "periodKey": query["periodKey"],
            }

    collections = {
        "users": FakeUsers(),
        "employees": FakeEmployees(),
        "email_master": FakeEmailMaster(),
        "achievement_awards": FakeAwards(),
        "achievement_periods": FakePeriods(),
    }

    with patch.object(
        service,
        "get_collection",
        side_effect=lambda name: collections[name],
    ):
        first = await service.archive_previous_achievement_period(
            datetime(2026, 11, 17, tzinfo=timezone.utc)
        )
        second = await service.archive_previous_achievement_period(
            datetime(2026, 11, 17, tzinfo=timezone.utc)
        )

    assert first == {"periodKey": "2026-09-26", "alreadyArchived": False}
    assert second == {"periodKey": "2026-09-26", "alreadyArchived": True}
    global_mail = next(
        board
        for board in stored_period["leaderboards"]
        if board["scope"] == "global" and board["metric"] == "mail"
    )
    assert [row["employeeId"] for row in global_mail["top3"]] == ["u6", "u5", "u1"]
    assert global_mail["top3"][0]["role"] == "super_admin"
    assert global_mail["top3"][1]["role"] == "admin"
    assert all(row["timesAchieved"] == 1 for row in global_mail["top3"])
    south_mail = next(
        board
        for board in stored_period["leaderboards"]
        if board["scope"] == "branch"
        and board["branchKey"] == "south"
        and board["metric"] == "mail"
    )
    assert south_mail["top3"][0]["employeeId"] == "u6"
    assert south_mail["top3"][0]["role"] == "super_admin"


@pytest.mark.anyio
async def test_leaderboard_users_include_all_roles_and_profile_picture_urls():
    has_picture_id = str(ObjectId())
    no_picture_id = str(ObjectId())
    admin_id = str(ObjectId())
    super_admin_id = str(ObjectId())
    marked_unknown_id = str(ObjectId())
    user_query = {}

    class FakeUsers:
        def find(self, query):
            user_query.update(query)
            return AsyncDocuments(
                [
                    {"_id": ObjectId(has_picture_id), "name": "Alex", "role": "employee"},
                    {"_id": ObjectId(no_picture_id), "name": "Bea", "role": "employee"},
                    {"_id": ObjectId(admin_id), "name": "Hari", "role": "admin"},
                    {"_id": ObjectId(super_admin_id), "name": "Super", "role": "super_admin"},
                    {
                        "_id": ObjectId(UNKNOWN_USER_ID),
                        "name": "Unknown",
                        "role": "employee",
                        "systemAccount": UNKNOWN_MARKER,
                    },
                    {
                        "_id": ObjectId(marked_unknown_id),
                        "name": "Unknown duplicate",
                        "role": "employee",
                        "systemAccount": UNKNOWN_MARKER,
                    },
                ]
            )

    class FakeEmployees:
        def find(self, _query, _projection):
            return AsyncDocuments([])

    with (
        patch.object(
            service,
            "get_collection",
            side_effect=lambda name: (
                FakeUsers() if name == "users" else FakeEmployees()
            ),
        ),
        patch(
            "app.users.service._profile_picture_url",
            side_effect=lambda user_id: (
                f"/users/{user_id}/profile-picture"
                if user_id == has_picture_id
                else None
            ),
        ),
    ):
        users = await service._load_leaderboard_users()

    assert user_query == {
        "role": {"$in": ["employee", "admin", "super_admin"]},
        "_id": {"$ne": ObjectId(UNKNOWN_USER_ID)},
        "systemAccount": {"$ne": UNKNOWN_MARKER},
    }
    assert UNKNOWN_USER_ID not in users
    assert marked_unknown_id not in users
    assert users[admin_id]["role"] == "admin"
    assert users[super_admin_id]["role"] == "super_admin"
    assert users[has_picture_id]["profilePictureUrl"] == (
        f"/users/{has_picture_id}/profile-picture"
    )
    assert users[no_picture_id]["profilePictureUrl"] is None


@pytest.mark.anyio
async def test_branch_leaderboard_returns_current_and_previous_top_three():
    users = {
        "u1": {"name": "Alex", "branch": "North"},
        "u2": {"name": "Bea", "branch": "North"},
        "u3": {"name": "Casey", "branch": "South"},
        UNKNOWN_USER_ID: {"name": "Unknown", "branch": "North"},
    }
    previous_rows = [
        {
            "employeeId": UNKNOWN_USER_ID,
            "employeeName": "Unknown",
            "branch": "North",
            "score": 99,
            "rank": 1,
        },
        {
            "employeeId": "u1",
            "employeeName": "Alex",
            "branch": "North",
            "score": 8,
            "rank": 1,
        },
        {
            "employeeId": "u2",
            "employeeName": "Bea",
            "branch": "North",
            "score": 5,
            "rank": 2,
        },
        {
            "employeeId": "u3",
            "employeeName": "Casey",
            "branch": "South",
            "score": 4,
            "rank": 3,
        },
    ]
    previous_doc = {
        "leaderboards": [
            {
                "scope": "branch",
                "branchKey": "north",
                "metric": "mail",
                "leaderboard": previous_rows,
                "top3": previous_rows[:3],
            }
        ]
    }

    class FakePeriods:
        async def find_one(self, _query, _projection):
            return previous_doc

    async def add_award_counts(rows, _scope, _branch_key, _metric):
        return [{**row, "timesAchieved": 2} for row in rows]

    with (
        patch.object(service, "archive_previous_achievement_period", new_callable=AsyncMock),
        patch.object(service, "_load_leaderboard_users", new_callable=AsyncMock, return_value=users),
        patch.object(
            service,
            "_get_period_counts",
            new_callable=AsyncMock,
            return_value=({"u1": 4, "u2": 2, "u3": 99}, {}),
        ),
        patch.object(service, "_add_award_counts", side_effect=add_award_counts),
        patch.object(service, "get_collection", return_value=FakePeriods()),
    ):
        result = await service.get_leaderboard(
            metric="mail",
            scope="branch",
            branch="North",
            now=datetime(2026, 11, 17, tzinfo=timezone.utc),
        )

    assert [row["employeeId"] for row in result["liveLeaderboard"]] == ["u1", "u2"]
    assert all(
        "profilePictureUrl" in row
        for row in result["liveLeaderboard"]
    )
    assert [row["employeeId"] for row in result["currentTop3"]] == ["u1", "u2"]
    assert [row["employeeId"] for row in result["previousTop3"]] == ["u1", "u2"]
    assert result["currentPeriod"]["finalized"] is False
    assert result["previousPeriod"]["finalized"] is True
    assert result["currentPeriod"]["startDateDisplay"] == "2026-10-26 12:00 AM"
    assert result["currentPeriod"]["endDateDisplay"] == "2026-11-25 12:00 AM"


@pytest.mark.anyio
async def test_custom_date_range_filters_live_board_but_keeps_monthly_top_three():
    user_id = "admin-1"
    users = {user_id: {"name": "Hari", "role": "admin", "branch": "North"}}
    period_calls = []
    now = datetime(2026, 11, 17, tzinfo=timezone.utc)

    async def get_period_counts(start, end_exclusive, _user_ids):
        period_calls.append((start, end_exclusive))
        if start == datetime(2026, 10, 26, tzinfo=timezone.utc):
            return {user_id: 20}, {user_id: 4}
        return {user_id: 2}, {user_id: 1}

    class FakePeriods:
        async def find_one(self, _query, _projection):
            return None

    async def add_award_counts(rows, _scope, _branch_key, _metric):
        return [{**row, "timesAchieved": 0} for row in rows]

    with (
        patch.object(service, "archive_previous_achievement_period", new_callable=AsyncMock),
        patch.object(service, "_load_leaderboard_users", new_callable=AsyncMock, return_value=users),
        patch.object(service, "_get_period_counts", side_effect=get_period_counts),
        patch.object(service, "_add_award_counts", side_effect=add_award_counts),
        patch.object(service, "get_collection", return_value=FakePeriods()),
    ):
        result = await service.get_leaderboard(
            metric="both",
            scope="global",
            branch=None,
            now=now,
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 10),
        )

    assert period_calls == [
        (
            datetime(2026, 10, 26, tzinfo=timezone.utc),
            datetime(2026, 11, 26, tzinfo=timezone.utc),
        ),
        (
            datetime(2026, 11, 1, tzinfo=timezone.utc),
            datetime(2026, 11, 11, tzinfo=timezone.utc),
        ),
    ]
    assert result["liveLeaderboard"][0]["score"] == 5.02
    assert result["currentTop3"][0]["score"] == 20.2
    assert result["livePeriod"]["startDate"] == "2026-11-01"
    assert result["livePeriod"]["endDate"] == "2026-11-10"
    assert result["currentPeriod"]["startDate"] == "2026-10-26"


@pytest.mark.anyio
async def test_custom_date_range_requires_both_dates_in_order():
    user = type("User", (), {"role": "super_admin"})()

    with pytest.raises(BadRequestException, match="provided together"):
        await get_achievements_leaderboard(
            startDate=date(2026, 11, 1),
            endDate=None,
            current_user=user,
        )

    with pytest.raises(BadRequestException, match="on or before"):
        await get_achievements_leaderboard(
            startDate=date(2026, 11, 11),
            endDate=date(2026, 11, 10),
            current_user=user,
        )


@pytest.mark.anyio
async def test_employee_gets_fixed_branch_live_board_and_current_top_three(monkeypatch):
    user_id = str(ObjectId())
    employee_data = {
        "scope": "branch",
        "branch": "North",
        "metric": "both",
        "livePeriod": {"startDate": "2026-10-26", "endDate": "2026-11-25"},
        "liveLeaderboard": [{"employeeId": user_id, "score": 5}],
        "currentPeriod": {"startDate": "2026-10-26", "endDate": "2026-11-25"},
        "currentTop3": [{"employeeId": user_id, "rank": 1}],
        "previousPeriod": {},
        "previousTop3": [],
    }

    class FakeCollection:
        async def find_one(self, query, _projection=None):
            if "userId" in query:
                return {"branch": "North"}
            return {"branch": "North"}

    monkeypatch.setattr("app.achievements.router.get_collection", lambda _name: FakeCollection())
    get_leaderboard = AsyncMock(return_value=employee_data)
    monkeypatch.setattr("app.achievements.router.service.get_leaderboard", get_leaderboard)

    response = await get_achievements_leaderboard(
        metric=None,
        scope=None,
        branch=None,
        startDate=None,
        endDate=None,
        current_user=CurrentUser(user_id, "employee"),
    )

    assert response.data == {
        "scope": "branch",
        "branch": "North",
        "metric": "both",
        "livePeriod": employee_data["livePeriod"],
        "liveLeaderboard": employee_data["liveLeaderboard"],
        "currentPeriod": employee_data["currentPeriod"],
        "currentTop3": employee_data["currentTop3"],
    }
    get_leaderboard.assert_awaited_once_with(
        metric="both",
        scope="branch",
        branch="North",
        permitted_user_ids=None,
        start_date=None,
        end_date=None,
    )


@pytest.mark.anyio
async def test_partial_admin_branch_board_includes_same_branch_super_admin(monkeypatch):
    admin_id = str(ObjectId())
    super_admin_id = str(ObjectId())
    requested_super_admin_query = {}

    class FakeEmployees:
        async def find_one(self, _query, _projection=None):
            return {"branch": "North"}

    class FakeUsers:
        async def find_one(self, _query, _projection=None):
            return {"branch": "North"}

        def find(self, query, _projection=None):
            requested_super_admin_query.update(query)
            return AsyncDocuments([{"_id": ObjectId(super_admin_id)}])

    employees = FakeEmployees()
    users = FakeUsers()
    monkeypatch.setattr(
        "app.achievements.router.get_collection",
        lambda name: employees if name == "employees" else users,
    )
    monkeypatch.setattr(
        "app.achievements.router._resolve_dashboard_scope",
        AsyncMock(return_value={"scope_user_ids": [admin_id]}),
    )
    get_leaderboard = AsyncMock(
        return_value={
            "scope": "branch",
            "branch": "North",
            "metric": "mail",
            "livePeriod": {},
            "liveLeaderboard": [],
            "currentPeriod": {},
            "currentTop3": [],
        }
    )
    monkeypatch.setattr(
        "app.achievements.router.service.get_leaderboard",
        get_leaderboard,
    )

    await get_achievements_leaderboard(
        metric=None,
        scope=None,
        branch=None,
        startDate=None,
        endDate=None,
        current_user=CurrentUser(admin_id, "admin", "partial"),
    )

    assert requested_super_admin_query["role"] == "super_admin"
    assert requested_super_admin_query["branch"] == {
        "$regex": "^North$",
        "$options": "i",
    }
    get_leaderboard.assert_awaited_once_with(
        metric="mail",
        scope="branch",
        branch="North",
        permitted_user_ids={admin_id, super_admin_id},
        start_date=None,
        end_date=None,
    )


@pytest.mark.anyio
async def test_employee_leaderboard_uses_current_user_branch_when_employee_copy_is_stale(
    monkeypatch,
):
    user_id = str(ObjectId())

    class FakeCollection:
        async def find_one(self, query, _projection=None):
            if "userId" in query:
                return {"branch": "Vellore"}
            return {"branch": "Chennai"}

    monkeypatch.setattr(
        "app.achievements.router.get_collection",
        lambda _name: FakeCollection(),
    )
    get_leaderboard = AsyncMock(
        return_value={
            "scope": "branch",
            "branch": "Chennai",
            "metric": "both",
            "livePeriod": {},
            "liveLeaderboard": [],
            "currentPeriod": {},
            "currentTop3": [],
            "previousPeriod": {},
            "previousTop3": [],
        }
    )
    monkeypatch.setattr(
        "app.achievements.router.service.get_leaderboard",
        get_leaderboard,
    )

    response = await get_achievements_leaderboard(
        metric=None,
        scope=None,
        branch=None,
        startDate=None,
        endDate=None,
        current_user=CurrentUser(user_id, "employee"),
    )

    assert response.data["branch"] == "Chennai"
    get_leaderboard.assert_awaited_once_with(
        metric="both",
        scope="branch",
        branch="Chennai",
        permitted_user_ids=None,
        start_date=None,
        end_date=None,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "filters",
    [
        {"metric": "mail"},
        {"scope": "global"},
        {"branch": "South"},
        {"startDate": date(2026, 11, 1)},
    ],
)
async def test_employee_cannot_apply_leaderboard_filters(filters):
    user = CurrentUser(str(ObjectId()), "employee")
    params = {
        "metric": None,
        "scope": None,
        "branch": None,
        "startDate": None,
        "endDate": None,
    }
    params.update(filters)

    with pytest.raises(BadRequestException, match="cannot apply leaderboard filters"):
        await get_achievements_leaderboard(**params, current_user=user)
