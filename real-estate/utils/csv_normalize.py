"""
Normalize Commercial Valuation CSV column names to match schema (cook_county.md).
Maps CSV headers like "class(es)", "1brunits", "adj_rent/sf" to class_es, _1brunits, adj_rent_sf.
"""

from typing import List
import pandas as pd


def normalize_column_name(col: str) -> str:
    """Normalize a column name for SQL/schema compatibility."""
    if not col or not isinstance(col, str):
        return col
    col = col.strip()
    col = col.replace("(", "_").replace(")", "")
    col = col.replace("/", "_").replace(":", "_")
    col = col.replace("%", "pct").replace(" ", "_")
    col = col.replace("#", "")
    if col and col[0].isdigit():
        col = "_" + col
    return col.lower()


def normalize_commercial_valuation_csv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize column names and add keypin_normalized.
    Returns a copy; does not mutate in place.
    """
    out = df.copy()
    out.columns = [normalize_column_name(c) for c in out.columns]
    if "keypin" in out.columns:
        keypin_str = out["keypin"].astype(str)
        out["keypin_normalized"] = keypin_str.str.replace("-", "").str.zfill(14)
    return out
