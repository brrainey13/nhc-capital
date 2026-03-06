"""
Normalize Commercial Valuation CSV column names to match schema (real_estate.md).
Maps CSV headers like "class(es)", "1brunits", "adj_rent/sf" to class_es, _1brunits, adj_rent_sf.
"""

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

    # Strip commas from all string columns that contain numeric-looking values with commas
    for col in out.columns:
        if out[col].dtype == object:
            try:
                str_col = out[col].astype(str)
                # If any value has a comma surrounded by digits, strip all commas
                if str_col.str.contains(r'\d,\d', na=False).any():
                    out[col] = str_col.str.replace(',', '', regex=False)
                    out[col] = out[col].replace({'nan': None, 'None': None, 'none': None})
            except Exception:
                pass
    return out
