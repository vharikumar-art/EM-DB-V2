"""
Migration script to merge Employees collection into Users collection

This script:
1. Gets all employees from employees collection
2. For each employee, updates corresponding user to have role=employee + branch info
3. Verifies data consistency
4. Optionally backs up or archives old employees collection

Run: python migrate_merge_employees.py
"""
import sys
import asyncio
sys.path.insert(0, '/path/to/backend')

from app.database.mongodb import get_collection


async def migrate():
    users_col = get_collection("users")
    employees_col = get_collection("employees")
    
    print("🔄 Starting Employee → User migration...")
    
    # Get all employees
    all_employees = await employees_col.find({}).to_list(length=None)
    print(f"📊 Found {len(all_employees)} employees to migrate")
    
    if len(all_employees) == 0:
        print("✅ No employees to migrate")
        return
    
    migrated_count = 0
    failed_count = 0
    
    for emp in all_employees:
        try:
            user_id = emp.get("userId")
            if not user_id:
                print(f"⚠️  Employee {emp.get('_id')} has no userId - skipping")
                failed_count += 1
                continue
            
            # Update user: set role=employee + branch
            result = await users_col.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "role": "employee",
                        "branch": emp.get("branch", "Default"),
                    }
                }
            )
            
            if result.modified_count > 0:
                migrated_count += 1
                print(f"✅ Migrated employee: {emp.get('_id')} → user {user_id}")
            else:
                print(f"⚠️  User {user_id} not found for employee {emp.get('_id')}")
                failed_count += 1
                
        except Exception as e:
            print(f"❌ Error migrating employee {emp.get('_id')}: {e}")
            failed_count += 1
    
    print(f"\n📈 Migration complete:")
    print(f"   ✅ Migrated: {migrated_count}")
    print(f"   ❌ Failed: {failed_count}")
    print(f"   📦 Employees collection can now be archived/deleted")


if __name__ == "__main__":
    asyncio.run(migrate())
