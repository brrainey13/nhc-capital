#!/usr/bin/env python3
"""
Kelly criterion bet sizing for NHL goalie saves bets.
Uses quarter Kelly by default for conservative bankroll management.
"""

import yaml
from pathlib import Path

DEPLOY_DIR = Path(__file__).parent

with open(DEPLOY_DIR / "config.yaml") as f:
    CONFIG = yaml.safe_load(f)


def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal payout (profit per $1 risked)."""
    if odds < 0:
        return 100 / abs(odds)
    else:
        return odds / 100


def kelly_fraction(win_prob: float, odds: int) -> float:
    """
    Calculate Kelly fraction: f* = (bp - q) / b
    where b = decimal payout, p = win probability, q = 1 - p
    """
    b = american_to_decimal(odds)
    p = win_prob
    q = 1 - p

    f = (b * p - q) / b
    return max(0, f)  # Never negative


def size_bet(
    win_prob: float,
    odds: int,
    bankroll: float = None,
    kelly_frac: float = None,
    max_bet: float = None,
) -> dict:
    """
    Calculate bet size using fractional Kelly.

    Returns dict with:
        full_kelly: Full Kelly fraction
        quarter_kelly: Our fraction
        bet_amount: Dollar amount to bet
        expected_value: EV per dollar
    """
    bankroll = bankroll or CONFIG["betting"]["bankroll"]
    kelly_frac = kelly_frac or CONFIG["betting"]["kelly_fraction"]
    max_bet = max_bet or CONFIG["betting"]["max_bet_per_game"]

    full_k = kelly_fraction(win_prob, odds)
    fractional_k = full_k * kelly_frac

    bet_amount = round(bankroll * fractional_k, 2)
    bet_amount = min(bet_amount, max_bet)
    bet_amount = max(bet_amount, 0)

    # EV calculation
    decimal_payout = american_to_decimal(odds)
    ev = win_prob * decimal_payout - (1 - win_prob)

    return {
        "full_kelly": round(full_k, 4),
        "fraction_kelly": round(fractional_k, 4),
        "bet_amount": bet_amount,
        "expected_value": round(ev, 4),
        "win_prob": win_prob,
        "odds": odds,
        "bankroll": bankroll,
    }


def estimate_win_prob(strategy: str, gap: float) -> float:
    """
    Estimate win probability based on strategy and gap size.
    Uses historical win rates from validated backtest.
    """
    # Base rates from audit results
    base_rates = {
        "MF3a": 0.705,  # Fold 1: 70.5%
        "MF3b": 0.580,  # Fold 2: 58.0% (conservative)
        "MF5": 0.621,   # Aggregate: 62.1%
        "MF2": 0.622,   # Aggregate: 62.2%
        "PF1": 0.592,   # From PROVENSTRATEGIES.md
    }

    base = base_rates.get(strategy, 0.55)

    # Adjust slightly for gap size (bigger gap = slightly higher confidence)
    # But cap at reasonable levels
    if strategy != "PF1":  # PF1 doesn't use gap
        if gap >= 2.5:
            base = min(base + 0.02, 0.75)
        elif gap >= 2.0:
            base = min(base + 0.01, 0.70)

    return base


if __name__ == "__main__":
    # Example
    for strategy in ["MF3a", "MF3b", "MF5", "MF2", "PF1"]:
        wp = estimate_win_prob(strategy, gap=1.5)
        result = size_bet(wp, -110)
        print(f"{strategy}: WP={wp:.1%}, Kelly={result['fraction_kelly']:.4f}, "
              f"Bet=${result['bet_amount']:.0f}, EV={result['expected_value']:+.4f}")
