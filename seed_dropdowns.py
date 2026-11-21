import asyncio
import os
import sys
from datetime import datetime, timezone
from bson import ObjectId

# Add backend directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

async def seed_dropdowns():
    print(f"Connecting to MongoDB: {settings.MONGO_DB_NAME}")
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]

    master = db["email_master"]
    employees_col = db["employees"]
    users_col = db["users"]
    filter_col = db["filter_dropdowns"]

    print("Fetching distinct values for dropdowns... This may take a while.")
    
    no_dup = {"isDuplicate": False}
    domains, domain_groups, countries, states, universities, designations, mail_sources = await asyncio.gather(
        master.distinct("domain", no_dup),
        master.distinct("domain_group", no_dup),
        master.distinct("country", no_dup),
        master.distinct("state", no_dup),
        master.distinct("university", no_dup),
        master.distinct("designation", no_dup),
        master.distinct("mailSource", no_dup),
    )

    print("Fetching uploaders...")
    uploaders_data: dict[str, str] = {}
    async for doc in master.find(
        {"uploadedBy": {"$exists": True, "$ne": None}},
        {"uploadedBy": 1, "uploadedByName": 1},
    ):
        uid = doc.get("uploadedBy")
        uname = doc.get("uploadedByName") or uid
        if uid and uid not in uploaders_data:
            uploaders_data[uid] = uname

    print("Fetching used_by_employees...")
    raw_used_emp: dict[str, str | None] = {}

    async for doc in master.find(
        {"usedByEmployeeId": {"$exists": True, "$ne": None}},
        {"usedByEmployeeId": 1, "usedByEmployeeName": 1},
    ):
        eid = doc.get("usedByEmployeeId")
        if eid and str(eid) not in raw_used_emp:
            raw_used_emp[str(eid)] = doc.get("usedByEmployeeName")

    async for doc in master.find(
        {"usedByEmployeeIds": {"$exists": True, "$not": {"$size": 0}}},
        {"usedByEmployeeIds": 1, "usedByEmployeeNames": 1},
    ):
        emp_ids = doc.get("usedByEmployeeIds", [])
        emp_names = doc.get("usedByEmployeeNames", [])
        for i, eid in enumerate(emp_ids):
            if eid and str(eid) not in raw_used_emp:
                raw_used_emp[str(eid)] = emp_names[i] if i < len(emp_names) else None

    async for doc in master.find(
        {"usedInProfiles": {"$exists": True, "$ne": []}},
        {"usedInProfiles": 1},
    ):
        for profile in doc.get("usedInProfiles", []):
            eid = profile.get("employeeId")
            if eid and str(eid) not in raw_used_emp:
                raw_used_emp[str(eid)] = None

    print("Resolving employee names...")
    unresolved_ids = [str(eid) for eid, name in raw_used_emp.items() if not name]
    if unresolved_ids:
        valid_obj_ids = [ObjectId(i) for i in unresolved_ids if ObjectId.is_valid(i)]
        emp_to_user: dict[str, str] = {}
        async for emp in employees_col.find(
            {"_id": {"$in": valid_obj_ids}}, {"_id": 1, "userId": 1}
        ):
            emp_to_user[str(emp["_id"])] = str(emp["userId"]) if emp.get("userId") else ""

        need_user_ids = [
            ObjectId(uid) for uid in {*emp_to_user.values(), *unresolved_ids}
            if uid and ObjectId.is_valid(uid)
        ]
        user_names: dict[str, str] = {}
        async for user in users_col.find(
            {"_id": {"$in": need_user_ids}}, {"_id": 1, "name": 1}
        ):
            user_names[str(user["_id"])] = user.get("name") or ""

        for eid in unresolved_ids:
            linked = emp_to_user.get(eid)
            name = (user_names.get(linked) if linked else None) or user_names.get(eid)
            if name:
                raw_used_emp[eid] = name

    unified_domains = sorted({v for v in [*domains, *domain_groups] if v})
    uploaders = [{"id": uid, "name": uname} for uid, uname in uploaders_data.items()]
    used_by_employees = [{"id": eid, "name": name or eid} for eid, name in raw_used_emp.items()]

    dropdown_doc = {
        "domains": unified_domains,
        "countries": [c for c in countries if c],
        "states": [s for s in states if s],
        "universities": [u for u in universities if u],
        "designations": [d for d in designations if d],
        "mailSources": [m for m in mail_sources if m],
        "uploaders": uploaders,
        "usedByEmployees": used_by_employees,
        "lastUpdated": datetime.now(timezone.utc)
    }

    print("Saving to filter_dropdowns collection...")
    await filter_col.update_one(
        {"_id": "global"},
        {"$set": dropdown_doc},
        upsert=True
    )
    print("Dropdown options successfully seeded!")
    client.close()

if __name__ == "__main__":
    asyncio.run(seed_dropdowns())
