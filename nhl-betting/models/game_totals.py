"""
Game Totals Model — Strategy D: Game Total OVER.

Triggered when multiple players from the same game qualify for OVER 1.5 pts,
signaling a high-scoring game environment. Bets the game total OVER instead
of stacking correlated player props.
"""
from models.player_points import calc_edge, kelly_size


def run_game_total_over(flagged_event_ids, game_totals_data):
    """Generate game total OVER picks for flagged high-scoring games.

    Args:
        flagged_event_ids: set of event_ids where 2+ players had OVER 1.5 edge
        game_totals_data: dict from odds_pull.pull_game_totals

    Returns:
        list of pick dicts
    """
    picks = []

    for eid in flagged_event_ids:
        if eid not in game_totals_data:
            continue

        total_info = game_totals_data[eid]
        total_line = total_info["total"]
        odds = total_info["odds"]

        # NHL average: ~6.1 goals/game (2025-26 season)
        # If line is 5.5 or 6.0, OVER hits ~55-58% historically
        # If line is 6.5, OVER hits ~45-48%
        # Use line-based historical hit rates as baseline
        if total_line <= 5.5:
            est_hit_rate = 0.58
        elif total_line <= 6.0:
            est_hit_rate = 0.53
        elif total_line <= 6.5:
            est_hit_rate = 0.47
        else:
            est_hit_rate = 0.42

        # Boost for model signal: multiple 1.5 qualifiers = high-scoring env
        # Conservative +3% boost (model-flagged games run hotter)
        adj_hit_rate = est_hit_rate + 0.03

        edge, breakeven = calc_edge(adj_hit_rate, odds)

        if edge > 0:
            units, dollars = kelly_size(edge, odds)
            confidence = "🟢 HIGH" if edge >= 0.05 else "🟡 MEDIUM"
            picks.append({
                "strategy": "D: Game Total OVER",
                "game": total_info["game"],
                "event_id": eid,
                "total": total_line,
                "odds": odds,
                "book": total_info["book"],
                "book_title": total_info["book_title"],
                "est_hit_rate": adj_hit_rate,
                "breakeven": breakeven,
                "edge": edge,
                "confidence": confidence,
                "units": units,
                "dollars": dollars,
                "reasoning": (
                    f"Multiple OVER 1.5 pt qualifiers in this game. "
                    f"Line {total_line}, adj hit rate "
                    f"{adj_hit_rate*100:.0f}%, "
                    f"BE {breakeven*100:.1f}%"
                ),
            })

    picks.sort(key=lambda x: -x["edge"])
    return picks
