"""Shared utilities for audit checks."""

import os
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

DB = os.environ.get("DATABASE_URL", "postgresql://nhc_agent@localhost:5432/nhl_betting")
MODEL_DIR = str(Path(__file__).resolve().parent)


def load_matrix():
    df = pd.read_pickle(f"{MODEL_DIR}/feature_matrix.pkl")
    df["event_date"] = pd.to_datetime(df["event_date"])
    return df
