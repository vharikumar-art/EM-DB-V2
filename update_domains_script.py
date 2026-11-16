import argparse
import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings


MAPPING_FILE = Path(__file__).with_name(
    "domain_name_mapping.json"
)


def load_domain_mapping() -> dict[str, tuple[str, set[str]]]:
    raw_mapping = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    if not isinstance(raw_mapping, dict):
        raise ValueError("Domain mapping must be a JSON object.")

    grouped: dict[str, tuple[str, set[str]]] = {}
    for source, target in raw_mapping.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("Domain mapping keys and values must be strings.")

        normalized_source = source.strip().upper()
        normalized_target = target.strip().upper()
        if not normalized_source or not normalized_target:
            raise ValueError("Domain mapping keys and values cannot be empty.")

        existing = grouped.get(normalized_source)
        if existing and existing[0] != normalized_target:
            raise ValueError(
                f"Conflicting targets for domain {normalized_source!r}."
            )
        if existing:
            existing[1].add(source)
        else:
            grouped[normalized_source] = (normalized_target, {source})

    return grouped


def order_sources(
    mapping: dict[str, tuple[str, set[str]]],
    counts: dict[str, int],
) -> list[str]:
    depths: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(source: str) -> int:
        if source in depths:
            return depths[source]
        if source in visiting:
            raise ValueError(f"Cyclic domain mapping detected at {source!r}.")

        visiting.add(source)
        target = mapping[source][0]
        result = 1 + depth(target) if target in mapping and target != source else 0
        visiting.remove(source)
        depths[source] = result
        return result

    for source in mapping:
        depth(source)

    return sorted(
        mapping,
        key=lambda source: (
            depths[source],
            (len(mapping[source][0]) - len(source)) * counts.get(source, 0),
            source,
        ),
    )


def safe_console_text(value: str) -> str:
    return value.encode("ascii", "backslashreplace").decode("ascii")


async def main(apply_changes: bool) -> None:
    mapping = load_domain_mapping()
    order_sources(mapping, {})
    client = AsyncIOMotorClient(settings.MONGO_URI)
    try:
        db = client[settings.MONGO_DB_NAME]
        collection = db["email_master"]
        filters = db["filter_dropdowns"]

        match_values = set(mapping)
        for _, source_values in mapping.values():
            match_values.update(source_values)

        pipeline = [
            {"$match": {"domain": {"$in": sorted(match_values)}}},
            {"$group": {"_id": "$domain", "count": {"$sum": 1}}},
        ]
        matched_domains = await collection.aggregate(pipeline).to_list(None)
        counts_by_source: dict[str, int] = defaultdict(int)
        total_to_update = 0
        for row in matched_domains:
            source = str(row["_id"]).strip().upper()
            target = mapping[source][0]
            count = row["count"]
            if source != target:
                counts_by_source[source] += count
                total_to_update += count

        print(f"Database: {settings.MONGO_DB_NAME}")
        print(f"Mapping entries: {len(mapping)}")
        print(f"Distinct source domains found: {len(counts_by_source)}")
        print(f"Email master records to update: {total_to_update}")
        for source, count in sorted(
            counts_by_source.items(), key=lambda item: (-item[1], item[0])
        )[:20]:
            print(f"  {source} -> {mapping[source][0]}: {count}")

        if not apply_changes:
            print("Dry run only. Re-run with --apply to update email_master.")
            return

        if not counts_by_source:
            print("No domain updates were necessary.")
        else:
            total_modified = 0
            for source in order_sources(mapping, counts_by_source):
                target, original_values = mapping[source]
                if source == target or source not in counts_by_source:
                    continue
                result = await collection.update_many(
                    {"domain": {"$in": sorted(original_values | {source})}},
                    {"$set": {"domain": target}},
                )
                total_modified += result.modified_count
                if result.modified_count:
                    print(
                        f"Updated '{safe_console_text(source)}' -> "
                        f"'{safe_console_text(target)}': "
                        f"{result.modified_count} records"
                    )
            print(f"Total email_master records updated: {total_modified}")

        domains = await collection.distinct("domain")
        clean_domains = sorted(
            {str(value).strip() for value in domains if value and str(value).strip()}
        )
        await filters.update_one(
            {"_id": "global"},
            {
                "$set": {
                    "domains": clean_domains,
                    "lastUpdated": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        print(f"Updated domain dropdown values: {len(clean_domains)}")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Normalize email_master domains using the verified JSON mapping."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply updates. Without this flag, only show a dry-run summary.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.apply))
