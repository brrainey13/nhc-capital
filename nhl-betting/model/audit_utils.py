"""Shared utilities for audit checks."""

import warnings
from pathlib import Path

import pandas as pd

try:
    from .db_config import get_database_url
except ImportError:
    from db_config import get_database_url

warnings.filterwarnings("ignore")

DB = get_database_url()
MODEL_DIR = str(Path(__file__).resolve().parent)


def load_matrix():
    df = pd.read_pickle(f"{MODEL_DIR}/feature_matrix.pkl")
    df["event_date"] = pd.to_datetime(df["event_date"])
    return df
