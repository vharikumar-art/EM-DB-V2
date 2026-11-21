import asyncio
import sys
import re
import pandas as pd
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

async def main():
    if len(sys.argv) < 2:
        print("Usage: python delete_emails.py <path_to_file>")
        sys.exit(1)
        
    file_path = sys.argv[1]
    
    emails_to_delete = set()
    email_regex = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    try:
        if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            df = pd.read_excel(file_path, header=None)
            for _, row in df.iterrows():
                for cell in row:
                    if pd.notna(cell):
                        # Find all emails in the cell (handling comma-separated values)
                        matches = email_regex.findall(str(cell))
                        for match in matches:
                            emails_to_delete.add(match.strip().lower())
        else:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    matches = email_regex.findall(line)
                    for match in matches:
                        emails_to_delete.add(match.strip().lower())
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        sys.exit(1)
        
    emails_list = list(emails_to_delete)
    if not emails_list:
        print("No valid emails found in the provided file.")
        sys.exit(0)
        
    print(f"Found {len(emails_list)} unique emails to delete.")

    # Connect to MongoDB
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]
    email_master_collection = db["email_master"]
    profile_emails_collection = db["profile_emails"]
    
    # Perform deletion
    try:
        # Delete from email_master
        result_master = await email_master_collection.delete_many({"email": {"$in": emails_list}})
        print(f"Deleted {result_master.deleted_count} emails from email_master collection.")
        
        # Delete from profile_emails
        result_profile = await profile_emails_collection.delete_many({"email": {"$in": emails_list}})
        print(f"Deleted {result_profile.deleted_count} emails from profile_emails collection.")
        
    except Exception as e:
        print(f"Error during deletion: {e}")
    finally:
        client.close()

if __name__ == "__main__":
    asyncio.run(main())
