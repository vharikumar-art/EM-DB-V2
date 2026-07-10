import io
from typing import Any

import pandas as pd

from app.utils.email_validator import is_valid_email, normalize_email

# Maps expected internal field -> list of acceptable header aliases (case-insensitive)
FIELD_ALIASES: dict[str, list[str]] = {
    "fullName": ["fullname", "full name", "name"],
    "email": ["email", "email address"],
    "company": ["company", "organization"],
    "website": ["website", "url"],
    "country": ["country"],
    "state": ["state", "province"],
    "city": ["city"],
    "domain": ["domain", "sector"],
    "industry": ["industry"],
    "designation": ["designation", "title", "job title"],
    "phone": ["phone", "phone number", "mobile"],
    "linkedin": ["linkedin", "linkedin url"],
    "citation": ["citation", "source citation", "reference"],
    "mailSource": ["mail source", "mailsource", "source", "email source"],
}


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
        if not is_valid_email(raw_email):
            record["email"] = raw_email
            invalid_rows.append(record)
            continue

        record["email"] = normalize_email(raw_email)
        valid_rows.append(record)

    return valid_rows, invalid_rows
