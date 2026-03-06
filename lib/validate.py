"""
Data validation helpers for NHC Capital.

All validators return a structured result dict:
    {"valid": bool, "errors": list[str], "details": dict}

Usage:
    from lib.validate import validate_not_null, validate_unique, validate_range

    result = validate_not_null(df, ["player_name", "game_id"])
    if not result["valid"]:
        print(result["errors"])
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Structured validation result."""
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"valid": self.valid, "errors": self.errors, "details": self.details}


def validate_not_null(df: Any, columns: list[str]) -> dict:
    """Check that specified columns have no null values."""
    result = ValidationResult()
    for col in columns:
        if col not in df.columns:
            result.valid = False
            result.errors.append(f"Column '{col}' not found in DataFrame")
            continue
        null_count = int(df[col].isnull().sum())
        if null_count > 0:
            result.valid = False
            result.errors.append(f"Column '{col}' has {null_count} null values")
            result.details[col] = {"null_count": null_count}
    return result.to_dict()


def validate_unique(df: Any, columns: list[str]) -> dict:
    """Check that specified columns (combined) have no duplicate rows."""
    result = ValidationResult()
    missing = [c for c in columns if c not in df.columns]
    if missing:
        result.valid = False
        result.errors.append(f"Columns not found: {missing}")
        return result.to_dict()

    dupes = df.duplicated(subset=columns, keep=False)
    dupe_count = int(dupes.sum())
    if dupe_count > 0:
        result.valid = False
        result.errors.append(
            f"Found {dupe_count} duplicate rows on columns {columns}"
        )
        result.details["duplicate_count"] = dupe_count
    return result.to_dict()


def validate_range(
    df: Any, column: str, min_val: float | None = None, max_val: float | None = None
) -> dict:
    """Check that values in a column fall within [min_val, max_val]."""
    result = ValidationResult()
    if column not in df.columns:
        result.valid = False
        result.errors.append(f"Column '{column}' not found")
        return result.to_dict()

    series = df[column].dropna()
    if min_val is not None:
        below = int((series < min_val).sum())
        if below > 0:
            result.valid = False
            result.errors.append(f"{below} values in '{column}' below minimum {min_val}")
            result.details["below_min"] = below

    if max_val is not None:
        above = int((series > max_val).sum())
        if above > 0:
            result.valid = False
            result.errors.append(f"{above} values in '{column}' above maximum {max_val}")
            result.details["above_max"] = above

    return result.to_dict()


def validate_schema_match(df: Any, table: str, db: str = "nhl_betting") -> dict:
    """Compare DataFrame columns against actual table schema."""
    from lib.ingest import get_table_columns

    result = ValidationResult()
    table_cols = set(get_table_columns(table, db))
    if not table_cols:
        result.valid = False
        result.errors.append(f"Table '{table}' not found or has no columns")
        return result.to_dict()

    df_cols = set(df.columns)
    extra = sorted(df_cols - table_cols)
    missing = sorted(table_cols - df_cols)

    if extra:
        result.valid = False
        result.errors.append(f"DataFrame has extra columns: {extra}")
    result.details["extra_columns"] = extra
    result.details["missing_columns"] = missing
    result.details["matched_columns"] = sorted(df_cols & table_cols)
    return result.to_dict()
