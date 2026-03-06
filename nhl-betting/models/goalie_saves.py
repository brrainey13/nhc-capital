"""Compatibility wrapper for the shared goalie saves model stack."""

from model.goalie_strategy import run_live_goalie_saves


def run_goalie_saves(best_odds, events, bankroll=None):
    """Preserve the legacy pipeline interface."""
    del best_odds
    return run_live_goalie_saves(events, bankroll=bankroll)
