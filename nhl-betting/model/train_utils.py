"""Shared utilities for model training pipeline."""

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

MODEL_DIR = Path(__file__).resolve().parent
RESULTS = {}


def load_matrix():
    matrix = pd.read_pickle(MODEL_DIR / 'feature_matrix.pkl')
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    return matrix


def walk_forward_split(matrix):
    """Walk-forward splits by season. Training STRICTLY before validation."""
    splits = [
        {
            'name': 'Train 22-23, Val 23-24',
            'train': matrix[matrix['event_date'] < '2023-10-01'],
            'val': matrix[(matrix['event_date'] >= '2023-10-01') & (matrix['event_date'] < '2024-10-01')],
        },
        {
            'name': 'Train 22-24, Val 24-25',
            'train': matrix[matrix['event_date'] < '2024-10-01'],
            'val': matrix[(matrix['event_date'] >= '2024-10-01') & (matrix['event_date'] < '2025-10-01')],
        },
        {
            'name': 'Train 22-25, Val 25-26',
            'train': matrix[matrix['event_date'] < '2025-10-01'],
            'val': matrix[matrix['event_date'] >= '2025-10-01'],
        },
    ]
    return [s for s in splits if len(s['train']) > 100 and len(s['val']) > 50]


def american_to_prob(odds):
    odds = np.array(odds, dtype=float)
    prob = np.where(odds < 0, -odds / (-odds + 100), 100 / (odds + 100))
    return prob


def calc_payout(odds):
    odds = np.array(odds, dtype=float)
    return np.where(odds < 0, 100 / (-odds), odds / 100)
