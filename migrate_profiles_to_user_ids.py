"""
Migration script to update existing profiles to use user_id instead of employee_id

This script:
1. Gets all profiles with old employeeId (from employees collection)
2. Looks up the corresponding user_id for each employee
3. Updates profile.employeeId to the user_id
4. Also updates any campaigns, profile_emails, etc. that reference employeeId

Run: python migrate_profiles_to_user_ids.py
"""
import sys
import asyncio
sys.path.insert(0, '/path/to/backend')

from app.database.mongodb import get_collection


async def migrate():
    users_col = get_collection("users")
    employees_col = get_collection("employees")
    profiles_col = get_collection("profiles")
    campaigns_col = get_collection("campaigns")
    profile_emails_col = get_collection("profile_emails")
    
    print("🔄 Starting profile migration (employeeId → userId)...")
    
    # Build mapping: old_employee_id -> new_user_id
    print("📊 Building employee → user mapping...")
    employee_to_user = {}
    all_employees = await employees_col.find({}).to_list(length=None)
    
    for emp in all_employees:
        emp_id = str(emp["_id"])
        user_id = emp.get("userId")
        if user_id:
            employee_to_user[emp_id] = user_id
            print(f"  ✓ Employee {emp_id[:12]}... → User {user_id[:12]}...")
    
    print(f"\n📈 Mapped {len(employee_to_user)} employees")
    
    if not employee_to_user:
        print("⚠️  No employees found - nothing to migrate")
        return
    
    # Migrate profiles
    print("\n🔄 Updating profiles...")
    profiles_updated = 0
    for old_emp_id, new_user_id in employee_to_user.items():
        result = await profiles_col.update_many(
            {"employeeId": old_emp_id},
            {"$set": {"employeeId": new_user_id}}
        )
        if result.modified_count > 0:
            profiles_updated += result.modified_count
            print(f"  ✓ Updated {result.modified_count} profiles")
    
    print(f"✅ Profiles updated: {profiles_updated}")
    
    # Migrate campaigns
    print("\n🔄 Updating campaigns...")
    campaigns_updated = 0
    for old_emp_id, new_user_id in employee_to_user.items():
        result = await campaigns_col.update_many(
            {"employeeId": old_emp_id},
            {"$set": {"employeeId": new_user_id}}
        )
        if result.modified_count > 0:
            campaigns_updated += result.modified_count
            print(f"  ✓ Updated {result.modified_count} campaigns")
    
    print(f"✅ Campaigns updated: {campaigns_updated}")
    
    # Migrate profile_emails
    print("\n🔄 Updating profile_emails...")
    pe_updated = 0
    for old_emp_id, new_user_id in employee_to_user.items():
        result = await profile_emails_col.update_many(
            {"employeeId": old_emp_id},
            {"$set": {"employeeId": new_user_id}}
        )
        if result.modified_count > 0:
            pe_updated += result.modified_count
            print(f"  ✓ Updated {result.modified_count} profile_emails")
    
    print(f"✅ Profile_emails updated: {pe_updated}")
    
    print(f"\n✨ Migration complete:")
    print(f"   📋 Profiles: {profiles_updated}")
    print(f"   📅 Campaigns: {campaigns_updated}")
    print(f"   📧 Profile Emails: {pe_updated}")
    print(f"\n✅ All collections now use user_id instead of employee_id")


if __name__ == "__main__":
    asyncio.run(migrate())
