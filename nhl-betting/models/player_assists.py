"""
Player Assists Model — UNDER 0.5 assists (Strategy B1).

Plus-money UNDER bets on low-assist players.
Auto-excludes players averaging >= 0.5 A/GP.
"""
from models.player_points import calc_edge, kelly_size


def run_assists_under(best_odds, player_stats, bankroll=None):
    """Generate UNDER 0.5 assist picks.

    Args:
        best_odds: dict from odds_pull.get_best_odds
        player_stats: dict of player stats keyed by player_id

    Returns:
        list of pick dicts sorted by edge
    """
    picks = []

    for (player, market, side, line), prop in best_odds.items():
        if market != "player_assists" or side != "Under" or line != 0.5:
            continue
        if prop["odds"] < 110:  # must be plus money
            continue

        stats = None
        for s in player_stats.values():
            if s["name"] == player:
                stats = s
                break
        if not stats or stats["gp"] < 10:
            continue

        # Screen out elite assisters
        if stats["apg"] >= 0.50:
            continue

        under_rate = 1 - stats["apg"]  # rough proxy
        odds = prop["odds"]
        edge, breakeven = calc_edge(under_rate, odds)

        if edge >= 0.03:
            units, dollars = kelly_size(edge=edge, odds=odds, bankroll=bankroll)
            confidence = "🟢 HIGH" if edge >= 0.10 else "🟡 MEDIUM"
            picks.append({
                **prop,
                "under_rate": under_rate,
                "apg": stats["apg"],
                "gp": stats["gp"],
                "breakeven": breakeven,
                "edge": edge,
                "confidence": confidence,
                "units": units,
                "dollars": dollars,
            })

    picks.sort(key=lambda x: -x["edge"])
    return picks[:10]  # Top 10 max
