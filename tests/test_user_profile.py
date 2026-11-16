import asyncio
from datetime import datetime

import pytest
from bson import ObjectId

from app.core.dependencies import CurrentUser
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.security import verify_password
from app.users import service
from app.users.schema import PasswordUpdate, UserProfileOut, UserUpdate
from app.utils.response import serialize_user


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


def test_admin_password_reset_stores_only_hash(monkeypatch):
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
    assert "passwordEncrypted" not in user
    assert "password" not in result


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


def test_admin_can_fetch_picture_for_an_employee_in_scope(monkeypatch, tmp_path):
    admin_id = ObjectId()
    user_id = ObjectId()
    employee_id = ObjectId()
    users = FakeUsersCollection({"_id": user_id, "role": "employee"})
    (tmp_path / str(user_id)).write_bytes(b"\x89PNG\r\n\x1a\ntest-image")
    monkeypatch.setattr(service.settings, "PROFILE_PICTURE_STORAGE_DIR", str(tmp_path))

    class FakeEmployeesCollection:
        async def find_one(self, query, projection=None):
            assert query == {"userId": str(user_id)}
            return {"_id": employee_id}

    def fake_get_collection(name):
        if name == "users":
            return users
        if name == "employees":
            return FakeEmployeesCollection()
        raise AssertionError(f"Unexpected collection: {name}")

    async def allow_scoped_employee(_current_user, requested_employee_id):
        assert requested_employee_id == str(employee_id)

    monkeypatch.setattr(service, "get_collection", fake_get_collection)
    monkeypatch.setattr(
        "app.core.dependencies.resolve_employee_context",
        allow_scoped_employee,
    )
    result = asyncio.run(
        service.get_admin_user_profile_picture(
            str(user_id),
            CurrentUser(str(admin_id), "admin"),
        )
    )

    assert result == (tmp_path / str(user_id), "image/png")


def test_admin_cannot_fetch_picture_for_another_admin(monkeypatch):
    admin_id = ObjectId()
    other_admin_id = ObjectId()
    users = FakeUsersCollection({"_id": other_admin_id, "role": "admin"})
    monkeypatch.setattr(service, "get_collection", lambda _name: users)

    with pytest.raises(ForbiddenException, match="access to this user's picture"):
        asyncio.run(
            service.get_admin_user_profile_picture(
                str(other_admin_id),
                CurrentUser(str(admin_id), "admin"),
            )
        )


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
