import asyncio
from datetime import datetime

import pytest
from bson import ObjectId

from app.core.dependencies import CurrentUser, get_current_user, require_admin
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.security import decrypt_password, encrypt_password, verify_password
from app.users import service
from app.users.router import get_user_profile_picture, router as users_router
from app.users.schema import PasswordUpdate, UserCreate, UserProfileOut, UserUpdate
from app.utils.response import serialize_list_users_with_password, serialize_user


class FakeUsersCollection:
    def __init__(self, user):
        self.user = user

    async def find_one(self, query, projection=None):
        return self.user if query.get("_id") == self.user["_id"] else None

    async def find_one_and_update(self, query, update, return_document=False):
        assert query.get("_id") == self.user["_id"]
        self.user.update(update.get("$set", {}))
        for field in update.get("$unset", {}):
            self.user.pop(field, None)
        return self.user


def test_user_serialization_never_exposes_passwords():
    user = serialize_user(
        {
            "_id": ObjectId(),
            "name": "Test User",
            "password": "hashed-password",
            "passwordEncrypted": "encrypted-password",
        }
    )

    assert "password" not in user
    assert "passwordEncrypted" not in user


def test_admin_user_list_includes_decrypted_password_only_in_list_serializer():
    docs = [
        {
            "_id": ObjectId(),
            "name": "Legacy-compatible user",
            "password": "hashed-password",
            "passwordEncrypted": encrypt_password("visible-to-admin-list"),
        },
        {
            "_id": ObjectId(),
            "name": "Hash-only user",
            "password": "hashed-password",
        },
    ]

    users = serialize_list_users_with_password(docs)

    assert users[0]["password"] == "visible-to-admin-list"
    assert users[1]["password"] is None
    assert "passwordEncrypted" not in users[0]
    assert "password" not in serialize_user(docs[0])


def test_new_user_document_keeps_encrypted_password_for_admin_list(monkeypatch):
    payload = UserCreate(
        name="New User",
        email="new@example.com",
        password="a-strong-password",
    )
    captured = {}

    class FakeUsersCollection:
        async def find_one(self, query):
            return None

        async def insert_one(self, doc):
            captured.update(doc)
            captured["_id"] = ObjectId()
            return type("InsertResult", (), {"inserted_id": captured["_id"]})()

    class FakeEmployeesCollection:
        async def insert_one(self, _doc):
            return None

    class FakeUserCollectionForRead(FakeUsersCollection):
        async def find_one(self, query):
            if query.get("_id") == captured.get("_id"):
                return captured
            return None

    collections = {
        "users": FakeUserCollectionForRead(),
        "employees": FakeEmployeesCollection(),
    }
    monkeypatch.setattr(service, "get_collection", lambda name: collections[name])

    created = asyncio.run(service.create_user(payload))

    assert created.get("password") is None
    assert serialize_list_users_with_password([captured])[0]["password"] == payload.password


def test_employee_cannot_edit_read_only_account_fields(monkeypatch):
    user_id = ObjectId()
    user = {"_id": user_id, "role": "employee"}
    monkeypatch.setattr(service, "get_collection", lambda _name: FakeUsersCollection(user))

    with pytest.raises(ForbiddenException, match="read-only"):
        asyncio.run(
            service.update_user(
                str(user_id),
                UserUpdate(name="Changed Name"),
                CurrentUser(str(user_id), "employee"),
            )
        )


def test_employee_cannot_change_password(monkeypatch):
    user_id = ObjectId()
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda _name: pytest.fail("Employee password changes must be rejected before DB access"),
    )

    with pytest.raises(ForbiddenException, match="cannot change"):
        asyncio.run(
            service.update_password(
                str(user_id),
                PasswordUpdate(old_password="old-password", new_password="new-password"),
                CurrentUser(str(user_id), "employee"),
            )
        )


def test_admin_password_reset_stores_hash_and_encrypted_value(monkeypatch):
    user_id = ObjectId()
    user = {
    "_id": user_id,
    "password": "old-hash",
    "passwordEncrypted": "old-encrypted-password",
    }
    monkeypatch.setattr(service, "get_collection", lambda _name: FakeUsersCollection(user))
    new_password = "new-secure-password"

    result = asyncio.run(
        service.reset_user_password(
            str(user_id),
            new_password,
            CurrentUser(str(user_id), "admin"),
        )
    )

    assert verify_password(new_password, user["password"])
    assert decrypt_password(user["passwordEncrypted"]) == new_password
    assert "password" not in result


def test_super_admin_can_change_another_users_password_without_old_password(monkeypatch):
    user_id = ObjectId()
    target = {
        "_id": user_id,
        "role": "employee",
        "password": "old-hash",
    }

    class UsersCollection(FakeUsersCollection):
        async def find_one(self, query, projection=None):
            return target if query.get("_id") == user_id else None

    monkeypatch.setattr(
        service,
        "get_collection",
        lambda _name: UsersCollection(target),
    )
    new_password = "new-secure-password"

    result = asyncio.run(
        service.update_password(
            str(user_id),
            PasswordUpdate(new_password=new_password),
            CurrentUser(str(ObjectId()), "super_admin"),
        )
    )

    assert verify_password(new_password, target["password"])
    assert "password" not in result


def test_full_admin_can_change_password_for_same_branch_employee(monkeypatch):
    admin_id = str(ObjectId())
    target_id = str(ObjectId())
    target_object_id = ObjectId(target_id)
    target = {
        "_id": target_object_id,
        "role": "employee",
        "branch": "Chennai",
        "password": "old-hash",
    }

    class UsersCollection:
        async def find_one(self, query, projection=None):
            if query.get("_id") == target_object_id:
                return target
            if query.get("_id") == ObjectId(admin_id):
                return {"branch": "Chennai"}
            return None

        async def find_one_and_update(self, query, update, return_document=False):
            assert query["_id"] == target_object_id
            target.update(update["$set"])
            return target

    class EmployeesCollection:
        async def find_one(self, query):
            return None

    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: UsersCollection() if name == "users" else EmployeesCollection(),
    )
    new_password = "new-secure-password"

    asyncio.run(
        service.update_password(
            target_id,
            PasswordUpdate(new_password=new_password),
            CurrentUser(admin_id, "admin", access_level="full"),
        )
    )

    assert verify_password(new_password, target["password"])


def test_full_admin_cannot_change_password_outside_own_branch(monkeypatch):
    admin_id = str(ObjectId())
    target_id = str(ObjectId())
    target = {
        "_id": ObjectId(target_id),
        "role": "employee",
        "branch": "Vellore",
        "password": "old-hash",
    }

    class UsersCollection:
        async def find_one(self, query, projection=None):
            if query.get("_id") == ObjectId(target_id):
                return target
            if query.get("_id") == ObjectId(admin_id):
                return {"branch": "Chennai"}
            return None

    class EmployeesCollection:
        async def find_one(self, _query):
            return None

    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: UsersCollection() if name == "users" else EmployeesCollection(),
    )

    with pytest.raises(ForbiddenException, match="in your branch"):
        asyncio.run(
            service.update_password(
                target_id,
                PasswordUpdate(new_password="new-secure-password"),
                CurrentUser(admin_id, "admin", access_level="full"),
            )
        )


def test_partial_admin_cannot_change_another_users_password(monkeypatch):
    admin_id = str(ObjectId())
    target_id = str(ObjectId())
    target = {
        "_id": ObjectId(target_id),
        "role": "employee",
        "branch": "Chennai",
    }

    class UsersCollection:
        async def find_one(self, query, projection=None):
            return target if query.get("_id") == ObjectId(target_id) else None

    monkeypatch.setattr(
        service,
        "get_collection",
        lambda _name: UsersCollection(),
    )

    with pytest.raises(ForbiddenException, match="Full access"):
        asyncio.run(
            service.update_password(
                target_id,
                PasswordUpdate(new_password="new-secure-password"),
                CurrentUser(admin_id, "admin", access_level="partial"),
            )
        )


def test_my_profile_returns_read_only_fields_without_credentials(monkeypatch, tmp_path):
    user_id = ObjectId()
    user = {
        "_id": user_id,
        "name": "Test User",
        "email": "test@example.com",
        "phoneNumber": "1234567890",
        "branch": "Vellore",
        "role": "employee",
        "status": "active",
        "createdAt": datetime(2026, 1, 1),
        "password": "hashed-password",
        "passwordEncrypted": "encrypted-password",
    }
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda _name: FakeUsersCollection(user),
    )
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))

    profile = asyncio.run(service.get_my_profile(str(user_id)))
    validated = UserProfileOut.model_validate(profile)

    assert validated.name == "Test User"
    assert validated.email == "test@example.com"
    assert validated.branch == "Vellore"
    assert validated.role == "employee"
    assert validated.profilePictureUrl is None
    assert validated.createdAt.endswith("Z")
    assert "password" not in profile
    assert "passwordEncrypted" not in profile


def test_my_profile_uses_users_branch_when_employee_copy_is_stale(
    monkeypatch,
    tmp_path,
):
    user_id = ObjectId()
    user = {
        "_id": user_id,
        "name": "Test User",
        "email": "test@example.com",
        "branch": "Chennai",
        "role": "employee",
    }

    class FakeEmployeesCollection:
        async def find_one(self, query, _projection=None):
            assert query == {"userId": str(user_id)}
            return {"branch": "Vellore"}

    collections = {
        "users": FakeUsersCollection(user),
        "employees": FakeEmployeesCollection(),
    }
    monkeypatch.setattr(
        service,
        "get_collection",
        lambda name: collections[name],
    )
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))

    profile = asyncio.run(service.get_my_profile(str(user_id)))

    assert profile["branch"] == "Chennai"


def test_profile_picture_is_stored_in_configured_directory(monkeypatch, tmp_path):
    user_id = ObjectId()
    user = {"_id": user_id}
    monkeypatch.setattr(service, "get_collection", lambda _name: FakeUsersCollection(user))
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))
    png = b"\x89PNG\r\n\x1a\n" + b"test-image"

    asyncio.run(service.save_profile_picture(str(user_id), png))

    path, media_type = service.get_profile_picture(str(user_id))
    assert path.parent == tmp_path
    assert path.read_bytes() == png
    assert media_type == "image/png"


def test_user_can_remove_own_profile_picture(monkeypatch, tmp_path):
    user_id = ObjectId()
    user = {"_id": user_id}
    picture_path = tmp_path / str(user_id)
    picture_path.write_bytes(b"\x89PNG\r\n\x1a\ntest-image")
    monkeypatch.setattr(service, "get_collection", lambda _name: FakeUsersCollection(user))
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))

    asyncio.run(service.remove_profile_picture(str(user_id)))

    assert not picture_path.exists()


def test_removing_missing_profile_picture_is_idempotent(monkeypatch, tmp_path):
    user_id = ObjectId()
    user = {"_id": user_id}
    monkeypatch.setattr(service, "get_collection", lambda _name: FakeUsersCollection(user))
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))

    asyncio.run(service.remove_profile_picture(str(user_id)))

    assert list(tmp_path.iterdir()) == []


def test_profile_picture_url_is_derived_from_file_and_user_id(monkeypatch, tmp_path):
    user_id = ObjectId()
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))

    assert service._profile_picture_url(str(user_id)) is None

    (tmp_path / str(user_id)).write_bytes(b"\x89PNG\r\n\x1a\ntest-image")

    assert service._profile_picture_url(str(user_id)) == (
        f"/users/{user_id}/profile-picture"
    )


def test_other_user_picture_route_requires_authentication_without_admin_role():
    route = next(
        route
        for route in users_router.routes
        if route.endpoint is get_user_profile_picture
    )

    assert any(
        dependency.call is get_current_user
        for dependency in route.dependant.dependencies
    )
    assert all(
        dependency.call is not require_admin
        for dependency in route.dependant.dependencies
    )


@pytest.mark.parametrize("target_role", ["employee", "admin", "super_admin"])
def test_authenticated_users_can_fetch_other_profile_pictures(
    monkeypatch,
    tmp_path,
    target_role,
):
    user_id = ObjectId()
    users = FakeUsersCollection({"_id": user_id, "role": target_role})
    (tmp_path / str(user_id)).write_bytes(b"\x89PNG\r\n\x1a\ntest-image")
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(service, "get_collection", lambda _name: users)

    result = asyncio.run(service.get_user_profile_picture(str(user_id)))

    assert result == (tmp_path / str(user_id), "image/png")


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (b"not an image", "JPEG, PNG, or WebP"),
        (b"\x89PNG\r\n\x1a\n" + b"x" * (service.PROFILE_PICTURE_MAX_BYTES + 1), "5 MB"),
    ],
    ids=["not-image", "too-large"],
)
def test_profile_picture_rejects_invalid_images(monkeypatch, tmp_path, contents, message):
    user_id = ObjectId()
    user = {"_id": user_id}
    monkeypatch.setattr(service, "get_collection", lambda _name: FakeUsersCollection(user))
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))

    with pytest.raises(BadRequestException, match=message):
        asyncio.run(service.save_profile_picture(str(user_id), contents))

    assert list(tmp_path.iterdir()) == []
