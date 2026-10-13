import asyncio
import sys
from datetime import datetime, timezone
from motor.motor_asyncio import AsyncIOMotorClient

# ==============================================================================
# CONFIGURATION: Replace these with your production credentials
# ==============================================================================
MONGO_URI = "mongodb+srv://Email_db_user:Hari%401234@emaildatabase.xzhhrz2.mongodb.net/EmailDataBase_Production?retryWrites=true&w=majority&appName=EmailDataBase_Production"
MONGO_DB_NAME = "EmailDataBase_Production"

COUNTRY_MAPPING = {
  "\"Oman\"": "OMAN",
  "\"Singapore\"": "SINGAPORE",
  ", Morocco": "MOROCCO",
  ".ae": "UNITED ARAB EMIRATES",
  ".in": "INDIA",
  "AU": "AUSTRALIA",
  "Abu Dhabi": "ABUDHABI",
  "Abu Dhabi Campus": "ABUDHABI",
  "Africa": "OTHERS",
  "Algeria": "ALGERIA",
  "American University in the Emirates": "OTHERS",
  "Assam, India": "INDIA",
  "Au": "AUSTRALIA",
  "Australia": "AUSTRALIA",
  "Australian": "AUSTRALIA",
  "BD": "BANGLADESH",
  "Bahrain": "BAHRAIN",
  "Bangaladesh": "BANGLADESH",
  "Bangladesh": "BANGLADESH",
  "Bd": "BANGLADESH",
  "Brazil": "BRAZIL",
  "British Indian Ocean Territory": "BRITISH INDIAN OCEAN TERRITORY",
  "CHINA": "CHINA",
  "CN": "CHINA",
  "Canada": "CANADA",
  "Chennai, TN, India": "INDIA",
  "Chian": "CHINA",
  "Chicago": "UNITED STATES",
  "Chiina": "CHINA",
  "China": "CHINA",
  "China, Pakistan": "CHINA",
  "Chins": "CHINA",
  "Chna": "CHINA",
  "City University College of Ajman": "OTHERS",
  "Coimbatore": "INDIA",
  "Colombia": "COLOMBIA",
  "Curtin University": "OTHERS",
  "Czechia": "CZECHIA",
  "Denmark": "DENMARK",
  "Dubai": "DUBAI",
  "Dubai, UAE": "DUBAI",
  "Dubhai": "DUBAI",
  "EGYPT": "EGYPT",
  "Egypt": "EGYPT",
  "Egypt, China": "EGYPT",
  "Egypt, Hungary": "EGYPT",
  "Egypt, Jordan": "EGYPT",
  "Egypt, Saudi Arabia": "EGYPT",
  "Egypt, UAE": "EGYPT",
  "Egypt, china": "EGYPT",
  "Finland": "FINLAND",
  "France": "FRANCE",
  "Fujairah Campus, Fujairah, UAE": "UNITED ARAB EMIRATES",
  "Germany": "GERMANY",
  "Greece": "GREECE",
  "Hong Kong": "HONG KONG",
  "Hong Kong, China": "HONG KONG",
  "Hong kong": "HONG KONG",
  "INDIA": "INDIA",
  "IRAN": "IRAN",
  "IRAQ": "IRAQ",
  "India": "INDIA",
  "India / 9828260098": "INDIA",
  "India, Ireland": "INDIA",
  "India, Israel": "INDIA",
  "India, Nigeria": "INDIA",
  "India, Sweden": "INDIA",
  "India, UAE": "INDIA",
  "India, china": "INDIA",
  "India, iraq": "INDIA",
  "India, japan": "INDIA",
  "India,saudi Arabia": "INDIA",
  "IndiaUnited Arab Emirates": "INDIA",
  "Indian Ocean Territory": "OTHERS",
  "Indonesia": "INDONESIA",
  "Iran": "IRAN",
  "Iran, Jordan": "IRAN",
  "Iraq": "IRAQ",
  "Israel": "ISRAEL",
  "Italy": "ITALY",
  "Japan": "JAPAN",
  "Jorda": "JORDAN",
  "Jordan": "JORDAN",
  "Jordan, Egypt": "JORDAN",
  "Jordan, India": "JORDAN",
  "Jordan, UAE": "JORDAN",
  "Jordan, uk": "JORDAN",
  "Kazakhstan": "KAZAKHSTAN",
  "Korea": "OTHERS",
  "Kuwait": "KUWAIT",
  "Libya": "LIBYA",
  "Malaysia": "MALAYSIA",
  "Moracco": "MOROCCO",
  "Morocco": "MOROCCO",
  "Morocco \"": "MOROCCO",
  "Morroccco": "MOROCCO",
  "Morrocco": "MOROCCO",
  "Nepal": "NEPAL",
  "Netherlands": "NETHERLANDS",
  "New York": "UNITED STATES",
  "New Zealand": "NEW ZEALAND",
  "Nigeria": "NIGERIA",
  "Norway": "NORWAY",
  "OMAN": "OMAN",
  "Oman": "OMAN",
  "Oman, Egypt": "OMAN",
  "Oman, Yemen": "OMAN",
  "Oman, india": "OMAN",
  "Omen": "OMAN",
  "PAKISTAN": "PAKISTAN",
  "PK": "PAKISTAN",
  "Pakistan": "PAKISTAN",
  "Pakistan, jordan": "PAKISTAN",
  "Palestine": "PALESTINE",
  "Paris, france": "FRANCE",
  "Pennsylvania": "UNITED STATES",
  "Pittsburgh": "UNITED STATES",
  "Portugal": "PORTUGAL",
  "QA": "QATAR",
  "Qartal": "QATAR",
  "Qatar": "QATAR",
  "Qater": "QATAR",
  "Republic of Korea": "SOUTH KOREA",
  "Russia": "RUSSIA",
  "S P Jain School of Global Management. Dubai": "OTHERS",
  "SA": "SAUDI ARABIA",
  "SAUDI ARABIA": "SAUDI ARABIA",
  "Saudi": "SAUDI ARABIA",
  "Saudi Arabi": "SAUDI ARABIA",
  "Saudi Arabia": "SAUDI ARABIA",
  "Saudi Arabia, Algeria": "SAUDI ARABIA",
  "Saudi Arabia, China": "SAUDI ARABIA",
  "Saudi Arabia, Egypt": "SAUDI ARABIA",
  "Saudi Arabia, Jordan": "SAUDI ARABIA",
  "Saudi Arabia, Tunisia": "SAUDI ARABIA",
  "Saudi Arabia, india": "SAUDI ARABIA",
  "Saudi Arabia,egypt": "SAUDI ARABIA",
  "Saudi Arabia.": "SAUDI ARABIA",
  "Saudi Arabia.,india": "SAUDI ARABIA",
  "Saudi Arabia; Egypt": "SAUDI ARABIA",
  "Saudi Arbia": "SAUDI ARABIA",
  "Saudi arabia": "SAUDI ARABIA",
  "Singapore": "SINGAPORE",
  "Slovakia": "SLOVAKIA",
  "Slovenia": "SLOVENIA",
  "Somalia": "SOMALIA",
  "South Africa": "SOUTH AFRICA",
  "South Korea": "SOUTH KOREA",
  "South korea": "SOUTH KOREA",
  "Spain": "SPAIN",
  "Springer Nature": "OTHERS",
  "Sri Lanka": "SRI LANKA",
  "Sudan": "SUDAN",
  "Swedan": "SWEDEN",
  "Sweden": "SWEDEN",
  "Switzerland": "SWITZERLAND",
  "Syria": "SYRIA",
  "Taiwan": "TAIWAN",
  "Tamil Nadu, India": "INDIA",
  "Telangana, India": "INDIA",
  "Th": "THAILAND",
  "Thailand.": "THAILAND",
  "Tunishia": "TUNISIA",
  "Tunisia": "TUNISIA",
  "Tunisia.\"": "TUNISIA",
  "UAE": "UNITED ARAB EMIRATES",
  "UAE, Egypt": "UNITED ARAB EMIRATES",
  "UK": "UNITED KINGDOM",
  "UNITED ARAB EMIRATES": "UNITED ARAB EMIRATES",
  "USA": "UNITED STATES",
  "Uae": "UNITED ARAB EMIRATES",
  "Uk": "UNITED KINGDOM",
  "United Arab Emirate": "UNITED ARAB EMIRATES",
  "United Arab Emirates": "UNITED ARAB EMIRATES",
  "United Arab sates": "OTHERS",
  "United Kingdom": "UNITED KINGDOM",
  "United States": "UNITED STATES",
  "United States of America": "UNITED STATES",
  "United kingdom": "UNITED KINGDOM",
  "Uzbekistan": "UZBEKISTAN",
  "Vietnam": "VIETNAM",
  "Yeman": "YEMEN",
  "Yemen": "YEMEN",
  "Yemen, china": "YEMEN",
  "ae": "UNITED ARAB EMIRATES",
  "africa": "OTHERS",
  "algeria": "ALGERIA",
  "at": "AUSTRIA",
  "australia": "AUSTRALIA",
  "bangaladesh": "BANGLADESH",
  "bangladesh": "BANGLADESH",
  "bd": "BANGLADESH",
  "bh": "BAHRAIN",
  "canada": "CANADA",
  "china": "CHINA",
  "china, pakistan": "CHINA",
  "cn": "CHINA",
  "dubai": "DUBAI",
  "dz": "ALGERIA",
  "edu": "OTHERS",
  "egypt": "EGYPT",
  "france": "FRANCE",
  "in": "INDIA",
  "indai": "INDIA",
  "india": "INDIA",
  "india\"": "INDIA",
  "indonasia": "INDONESIA",
  "indonesia": "INDONESIA",
  "iq": "IRAQ",
  "ir": "IRAN",
  "iran": "IRAN",
  "iran.": "IRAN",
  "iraq": "IRAQ",
  "iraq.": "IRAQ",
  "israel": "ISRAEL",
  "japan": "JAPAN",
  "jo": "JORDAN",
  "jordan": "JORDAN",
  "jorden": "JORDAN",
  "jp": "JAPAN",
  "korea": "OTHERS",
  "kr": "SOUTH KOREA",
  "kwith": "KUWAIT",
  "lebanon": "LEBANON",
  "ly": "LIBYA",
  "malasia": "MALAYSIA",
  "malasiya": "MALAYSIA",
  "malasiya\"": "MALAYSIA",
  "malaysia": "MALAYSIA",
  "moracco": "MOROCCO",
  "my": "MALAYSIA",
  "nepal": "NEPAL",
  "netherland": "NETHERLANDS",
  "nigeria": "NIGERIA",
  "nited Arab Emirates": "UNITED ARAB EMIRATES",
  "north africa": "OTHERS",
  "oman": "OMAN",
  "oman, Yemen": "OMAN",
  "omen": "OMAN",
  "pakistan": "PAKISTAN",
  "pakisthan": "PAKISTAN",
  "palestine": "PALESTINE",
  "ph": "PHILIPPINES",
  "pk": "PAKISTAN",
  "poakistan": "PAKISTAN",
  "poland": "POLAND",
  "portugal": "PORTUGAL",
  "ps": "PALESTINE",
  "qatar": "QATAR",
  "raq": "IRAQ",
  "sa": "SAUDI ARABIA",
  "saudi": "SAUDI ARABIA",
  "saudi Arabia": "SAUDI ARABIA",
  "saudi arabia": "SAUDI ARABIA",
  "saudi arabia, Morocco": "SAUDI ARABIA",
  "saudiarabia": "SAUDI ARABIA",
  "se": "SWEDEN",
  "serbia": "SERBIA",
  "sg": "SINGAPORE",
  "siberia": "OTHERS",
  "singapore": "SINGAPORE",
  "soudi": "SAUDI ARABIA",
  "south korea": "SOUTH KOREA",
  "spain": "SPAIN",
  "sri lanka": "SRI LANKA",
  "srilanka": "SRI LANKA",
  "sudan": "SUDAN",
  "sudan, Yemen": "SUDAN",
  "sweden": "SWEDEN",
  "taiwan": "TAIWAN",
  "tiwan": "TAIWAN",
  "turkey": "TURKEY",
  "tw": "TAIWAN",
  "uAE": "UNITED ARAB EMIRATES",
  "uae": "UNITED ARAB EMIRATES",
  "uk": "UNITED KINGDOM",
  "ukrine": "UKRAINE",
  "united arab emirates": "UNITED ARAB EMIRATES",
  "use": "OTHERS",
  "vietnam": "VIETNAM",
  "yamen": "YEMEN",
  "yeman": "YEMEN",
  "yemen": "YEMEN",
  "za": "SOUTH AFRICA"
}

async def rebuild_dropdowns(db):
    """Rebuild the frontend dropdown filter cache by scanning the database."""
    print("Rebuilding filter dropdowns from email_master (this may take a moment)...")
    master = db["email_master"]
    filter_col = db["filter_dropdowns"]

    pipeline = [
        {
            "$group": {
                "_id": None,
                "countries":      {"$addToSet": "$country"},
                "states":         {"$addToSet": "$state"},
                "universities":   {"$addToSet": "$university"},
                "designations":   {"$addToSet": "$designation"},
                "mailSources":    {"$addToSet": "$mailSource"},
                "domains":        {"$addToSet": "$domain"},
                "domain_groups":  {"$addToSet": "$domain_group"},
            }
        }
    ]

    result = await master.aggregate(pipeline).to_list(1)

    def _clean(values: list) -> list:
        return sorted({str(v).strip() for v in (values or []) if v and str(v).strip()})

    if result:
        row = result[0]
        all_domains = _clean((row.get("domains") or []) + (row.get("domain_groups") or []))

        # Build update structure
        update_data = {
            "countries": _clean(row.get("countries")),
            "states": _clean(row.get("states")),
            "universities": _clean(row.get("universities")),
            "designations": _clean(row.get("designations")),
            "mailSources": _clean(row.get("mailSources")),
            "domains": all_domains,
        }

        # Filter out empty lists
        update_data = {k: v for k, v in update_data.items() if v}

        if update_data:
            await filter_col.update_one(
                {"_id": "global"},
                {
                    "$set": {
                        **update_data,
                        "lastUpdated": datetime.now(timezone.utc)
                    }
                },
                upsert=True
            )
            print("Dropdown filters updated successfully.")
    else:
        print("No data found in email_master to rebuild dropdowns.")

async def main():
    if not MONGO_URI or MONGO_URI == "your_production_mongo_uri_here":
        print("ERROR: Please edit the script and set MONGO_URI and MONGO_DB_NAME on lines 7 and 8.")
        sys.exit(1)

    print("Connecting to MongoDB...")
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    collection = db["email_master"]

    print("Starting country update process...")
    
    total_updated = 0
    
    # Loop over mapping and execute updates
    for old_country, new_country in COUNTRY_MAPPING.items():
        result = await collection.update_many(
            {"country": old_country},
            {"$set": {"country": new_country}}
        )
        if result.modified_count > 0:
            print(f"Updated '{old_country}' -> '{new_country}': {result.modified_count} records")
            total_updated += result.modified_count

    print(f"Total records updated: {total_updated}")
    
    # Refetch/Rebuild the dropdowns globally so the frontend shows the correct list
    await rebuild_dropdowns(db)
    
    print("Done! You may need to refresh your browser page to see the updated dropdown list if it was cached locally.")

if __name__ == "__main__":
    asyncio.run(main())
