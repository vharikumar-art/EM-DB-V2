import io
import re
from typing import Any

import pandas as pd

from app.utils.email_validator import is_valid_email, normalize_email

ALLOWED_DOMAIN_GROUPS: list[str] = [
    "IT",
    "Data Science",
    "Agriculture",
    "Engineering",
    "Business",
    "Management",
    "Finance",
    "Computer Science",
    "Electronics",
    "Medicine",
]

DOMAIN_GROUP_ALIASES: dict[str, str] = {
    "it": "IT",
    "data science": "Data Science",
    "data-science": "Data Science",
    "computer science": "Computer Science",
    "cs": "Computer Science",
    "agri": "Agriculture",
    "agriculture": "Agriculture",
    "engineering": "Engineering",
    "eng": "Engineering",
    "business": "Business",
    "management": "Management",
    "finance": "Finance",
    "electronics": "Electronics",
    "medicine": "Medicine",
    "health": "Medicine",
    "healthcare": "Medicine",
}

# Maps expected internal field -> list of acceptable header aliases (case-insensitive)
FIELD_ALIASES: dict[str, list[str]] = {
    "fullName": ["fullname", "full name", "name"],
    "email": ["email", "email address"],
    "university": ["university", "organization"],
    "website": ["website", "url"],
    "country": ["country"],
    "state": ["state", "province"],
    "city": ["city"],
    "domain": ["domain", "sector"],
    "domain_group": ["domain_group", "domain group", "field category", "field_group"],
    "industry": ["industry"],
    "designation": ["designation", "title", "job title"],
    "phone": ["phone", "phone number", "mobile"],
    "linkedin": ["linkedin", "linkedin url"],
    "citation": ["citation", "source citation", "reference"],
    "mailSource": ["mail source", "mailsource", "source", "email source"],
}


def normalize_domain_group(raw_value: str | None) -> list[str]:
    """Normalize category-like values such as 'IT, Data Science' into canonical labels."""
    if raw_value is None:
        return []

    text = str(raw_value).strip()
    if not text:
        return []

    normalized_text = re.sub(r"\s*(?:,|;|/|\||\n|&|\band\b)\s*", "|", text, flags=re.IGNORECASE)
    normalized_text = re.sub(r"[-_]+", " ", normalized_text)
    chunks = [chunk.strip() for chunk in normalized_text.split("|") if chunk and chunk.strip()]

    result: list[str] = []
    seen: set[str] = set()

    for chunk in chunks:
        candidate = re.sub(r"\s+", " ", chunk).strip().lower()
        if not candidate:
            continue

        canonical = DOMAIN_GROUP_ALIASES.get(candidate)
        if canonical is None:
            for allowed in ALLOWED_DOMAIN_GROUPS:
                allowed_key = allowed.lower()
                if candidate == allowed_key:
                    canonical = allowed
                    break
                if candidate.replace(" ", "") == allowed_key.replace(" ", ""):
                    canonical = allowed
                    break

        if canonical and canonical not in seen:
            result.append(canonical)
            seen.add(canonical)

    return result


def _map_headers(columns: list[str]) -> dict[str, str]:
    """Return mapping of actual CSV column name -> normalized internal field name."""
    lookup: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            lookup[alias.lower().strip()] = field

    mapping: dict[str, str] = {}
    for col in columns:
        key = col.lower().strip()
        if key in lookup:
            mapping[col] = lookup[key]
    return mapping


def parse_file_bytes(file_bytes: bytes, filename: str) -> pd.DataFrame:
    try:
        if filename.lower().endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
        else:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Unable to parse file: {exc}") from exc

    header_map = _map_headers(list(df.columns))
    if "email" not in header_map.values():
        raise ValueError(f"File must contain an 'email' column. Found columns: {list(df.columns)}")

    df = df.rename(columns=header_map)
    # Keep only recognized columns
    keep_cols = [c for c in FIELD_ALIASES.keys() if c in df.columns]
    df = df[keep_cols]
    return df


def validate_and_clean_rows(df: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Returns (valid_rows, invalid_rows).
    Each valid row is a dict ready for duplicate checking / insertion.
    """
    valid_rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []

    for _, row in df.iterrows():
        raw_email = str(row.get("email", "")).strip()
        record = {field: (str(row[field]).strip() if field in df.columns else "") for field in FIELD_ALIASES}

        raw_domain_group = record.get("domain_group") or row.get("domain_group") or row.get("domain", "")
        record["domain_group"] = normalize_domain_group(raw_domain_group)

        if not is_valid_email(raw_email):
            record["email"] = raw_email
            invalid_rows.append(record)
            continue

        record["email"] = normalize_email(raw_email)
        valid_rows.append(record)

    return valid_rows, invalid_rows
