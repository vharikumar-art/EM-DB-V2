import argparse
import asyncio
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from bson import decode_file_iter
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne

from app.core.config import settings


EXPECTED_DATABASE = "EmailDataBase_Production"
SOURCE_BACKUP = Path(
    r"D:\MongoBackups\2026-11-12\EmailDataBase_Production"
)
CURRENT_BACKUP = Path(
    r"D:\MongoBackups_1\2026-11-14\EmailDataBase_Production"
)
TAMIL_NADU_VALUES = {"TAMIL NADU", "TAMILNADU"}
BATCH_SIZE = 1000


def normalize_email(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().casefold()


def normalize_state(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().upper()


def load_state_mapping(source_path: Path) -> dict[str, str]:
    mapping: dict[str, set[str]] = defaultdict(set)
    with source_path.open("rb") as source:
        for doc in decode_file_iter(source):
            email = normalize_email(doc.get("email"))
            state = normalize_state(doc.get("state"))
            if email and state:
                mapping[email].add(state)

    conflicts = {
        email: states for email, states in mapping.items() if len(states) > 1
    }
    if conflicts:
        raise ValueError(
            f"Source backup has {len(conflicts)} email addresses with "
            "conflicting states; refusing to update."
        )
    return {email: next(iter(states)) for email, states in mapping.items()}


def count_bson_documents(path: Path) -> int:
    with path.open("rb") as source:
        return sum(1 for _ in decode_file_iter(source))


def load_backup_keys(path: Path) -> set[tuple[object, str | None]]:
    keys: set[tuple[object, str | None]] = set()
    with path.open("rb") as source:
        for doc in decode_file_iter(source):
            keys.add((doc["_id"], normalize_email(doc.get("email"))))
    return keys


async def load_collection_keys(collection) -> set[tuple[object, str | None]]:
    keys: set[tuple[object, str | None]] = set()
    async for doc in collection.find({}, {"email": 1}):
        keys.add((doc["_id"], normalize_email(doc.get("email"))))
    return keys


def target_master_state(
    doc: dict,
    state_mapping: dict[str, str],
) -> str:
    email = normalize_email(doc.get("email"))
    return state_mapping.get(email, "") if email else ""


def target_profile_state(
    doc: dict,
    state_mapping: dict[str, str],
) -> str:
    state = normalize_state(doc.get("state"))
    if state in TAMIL_NADU_VALUES:
        email = normalize_email(doc.get("email"))
        return state_mapping.get(email, "") if email else ""
    return state or ""


def make_update(doc: dict, target_state: str) -> UpdateOne:
    query = {"_id": doc["_id"]}
    query["email"] = doc["email"] if "email" in doc else {"$exists": False}
    query["state"] = doc["state"] if "state" in doc else {"$exists": False}
    return UpdateOne(query, {"$set": {"state": target_state}})


async def preview_collection(
    collection,
    target_for: Callable[[dict], str],
) -> Counter:
    counts = Counter()
    async for doc in collection.find({}, {"email": 1, "state": 1}):
        counts["total"] += 1
        target_state = target_for(doc)
        if target_state:
            counts["target_nonempty"] += 1
        else:
            counts["target_empty"] += 1
        if doc.get("state") != target_state:
            counts["would_update"] += 1
    return counts


async def apply_collection(
    collection,
    target_for: Callable[[dict], str],
) -> int:
    operations: list[UpdateOne] = []
    modified = 0
    async for doc in collection.find({}, {"email": 1, "state": 1}):
        target_state = target_for(doc)
        if doc.get("state") == target_state:
            continue
        operations.append(make_update(doc, target_state))
        if len(operations) >= BATCH_SIZE:
            result = await collection.bulk_write(operations, ordered=False)
            modified += result.modified_count
            operations.clear()

    if operations:
        result = await collection.bulk_write(operations, ordered=False)
        modified += result.modified_count
    return modified


async def verify_collection(
    collection,
    target_for: Callable[[dict], str],
) -> Counter:
    counts = Counter()
    async for doc in collection.find({}, {"email": 1, "state": 1}):
        counts["total"] += 1
        expected = target_for(doc)
        actual = doc.get("state", "")
        if actual != expected:
            counts["mismatched"] += 1
        if isinstance(actual, str) and actual and actual != actual.upper():
            counts["not_uppercase"] += 1
    return counts


async def main(apply_changes: bool) -> None:
    if settings.MONGO_DB_NAME != EXPECTED_DATABASE:
        raise RuntimeError(
            "Configured database does not match the expected production database; "
            "refusing to continue."
        )

    source_bson = SOURCE_BACKUP / "email_master.bson"
    current_master_bson = CURRENT_BACKUP / "email_master.bson"
    current_profile_bson = CURRENT_BACKUP / "profile_emails.bson"
    for path in (source_bson, current_master_bson, current_profile_bson):
        if not path.is_file():
            raise FileNotFoundError(f"Required backup file not found: {path}")

    source_master_count = count_bson_documents(source_bson)
    current_master_count = count_bson_documents(current_master_bson)
    current_profile_count = count_bson_documents(current_profile_bson)
    current_master_keys = load_backup_keys(current_master_bson)
    current_profile_keys = load_backup_keys(current_profile_bson)
    state_mapping = load_state_mapping(source_bson)

    client = AsyncIOMotorClient(
        settings.MONGO_URI,
        serverSelectionTimeoutMS=12000,
        connectTimeoutMS=12000,
    )
    try:
        await client.admin.command("ping")
        db = client[settings.MONGO_DB_NAME]
        master = db["email_master"]
        profile_emails = db["profile_emails"]

        live_master_count = await master.count_documents({})
        live_profile_count = await profile_emails.count_documents({})
        if (
            live_master_count != current_master_count
            or live_profile_count != current_profile_count
        ):
            raise RuntimeError(
                "Live collection counts differ from the current backup; "
                "refusing to apply the repair."
            )
        if (
            await load_collection_keys(master) != current_master_keys
            or await load_collection_keys(profile_emails) != current_profile_keys
        ):
            raise RuntimeError(
                "Live collection records differ from the current backup; "
                "refusing to apply the repair."
            )

        master_target = lambda doc: target_master_state(doc, state_mapping)
        profile_target = lambda doc: target_profile_state(doc, state_mapping)
        master_preview = await preview_collection(master, master_target)
        profile_preview = await preview_collection(profile_emails, profile_target)

        print(f"Database: {settings.MONGO_DB_NAME}")
        print(f"Source backup email_master documents: {source_master_count}")
        print(f"Source emails with one recoverable state: {len(state_mapping)}")
        print(f"Current backup email_master documents: {current_master_count}")
        print(f"Current backup profile_emails documents: {current_profile_count}")
        print("Live record identities match the current backup.")
        print(f"email_master preview: {dict(master_preview)}")
        print(f"profile_emails preview: {dict(profile_preview)}")

        if not apply_changes:
            print("Dry run only. Re-run with --apply to write the state corrections.")
            return

        master_modified = await apply_collection(master, master_target)
        profile_modified = await apply_collection(profile_emails, profile_target)
        master_check = await verify_collection(master, master_target)
        profile_check = await verify_collection(profile_emails, profile_target)
        master_verification = {
            key: master_check.get(key, 0)
            for key in ("total", "mismatched", "not_uppercase")
        }
        profile_verification = {
            key: profile_check.get(key, 0)
            for key in ("total", "mismatched", "not_uppercase")
        }

        print(f"email_master documents modified: {master_modified}")
        print(f"profile_emails documents modified: {profile_modified}")
        print(f"email_master verification: {master_verification}")
        print(f"profile_emails verification: {profile_verification}")

        if master_check["mismatched"] or master_check["not_uppercase"]:
            raise RuntimeError("email_master verification failed.")
        if profile_check["mismatched"] or profile_check["not_uppercase"]:
            raise RuntimeError("profile_emails verification failed.")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Restore states by email from a MongoDB BSON backup."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates. Without this flag, run a read-only preview.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.apply))
