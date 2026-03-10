"""
Steam Detector — Identifies line movement signals from BettingPros data.

Compares opening odds to current odds for player props. When lines move
significantly toward Over (sharps loading), flags as steam confirmation.
When lines move toward Under, flags as steam fade.

Based on backtest of 1,676 player-game lines (2025-26 season):
  - Lines moving 20+ cents toward Over: 55.7% hit rate
  - Stable lines (<10 cent move): 44.1% hit rate
  - Lines moving 20+ toward Under: 36.1% hit rate

Usage:
    from pipeline.steam_detector import get_steam_signals, annotate_picks
"""

from __future__ import annotations

import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import psycopg2
from model.db_config import get_dsn

log = logging.getLogger(__name__)

# Thresholds (calibrated from backtest)
STRONG_STEAM_THRESHOLD = 20   # cents — 55.7% hit rate historically
MILD_STEAM_THRESHOLD = 10     # cents — 52.2% hit rate
FADE_THRESHOLD = -10          # cents — line moving toward Under
STRONG_FADE_THRESHOLD = -20   # cents — 36.1% hit rate


def _get_conn():
    """Get read-only DB connection."""
    dsn = get_dsn()
    return psycopg2.connect(dsn)


def get_steam_signals(target_date: str, market: str = "points") -> dict:
    """Pull opening vs current odds from BettingPros for a given date.

    Returns dict keyed by (player_name_lower, line) with steam data:
        {
            "player_name": str,
            "line": float,
            "open_odds": int,      # DraftKings opening odds
            "close_odds": int,     # DraftKings current odds
            "move": int,           # close - open (negative = steamed toward Over)
            "signal": str,         # "strong_steam" | "mild_steam" | "neutral" | "mild_fade" | "strong_fade"
            "books": dict,         # {book_name: over_odds}
            "best_book": str,
            "best_odds": int,
            "hr_edge": int | None, # Hard Rock odds - DraftKings odds
        }
    """
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT player_name, line, book_name, over_odds,
               opening_over_odds
        FROM bp_player_odds
        WHERE event_date = %s AND market = %s
          AND over_odds IS NOT NULL
        ORDER BY player_name, book_name
        """,
        (target_date, market),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        log.warning(f"No BettingPros data for {target_date} / {market}")
        return {}

    # Group by player + line
    grouped: dict[tuple, list] = defaultdict(list)
    for player_name, line, book_name, over_odds, opening_odds in rows:
        key = (player_name.lower().strip(), float(line))
        grouped[key].append({
            "player_name": player_name,
            "book": book_name,
            "over_odds": int(over_odds),
            "opening": int(opening_odds) if opening_odds else None,
        })

    signals = {}
    for (name_lower, line), entries in grouped.items():
        books = {e["book"]: e["over_odds"] for e in entries}

        # Use DraftKings for steam detection (most liquid)
        dk = next((e for e in entries if e["book"] == "draftkings"), None)
        hr = next((e for e in entries if e["book"] == "hardrock"), None)

        open_odds = dk["opening"] if dk and dk["opening"] else None
        close_odds = dk["over_odds"] if dk else None

        # Compute move
        if open_odds is not None and close_odds is not None:
            move = close_odds - open_odds
        else:
            move = 0

        # Classify signal
        if move <= -STRONG_STEAM_THRESHOLD:
            signal = "strong_steam"
        elif move <= -MILD_STEAM_THRESHOLD:
            signal = "mild_steam"
        elif move >= STRONG_STEAM_THRESHOLD:
            signal = "strong_fade"
        elif move >= MILD_STEAM_THRESHOLD:
            signal = "mild_fade"
        else:
            signal = "neutral"

        # Best book
        best_book = max(books, key=books.get) if books else None
        best_odds = books[best_book] if best_book else None

        # Hard Rock edge
        hr_edge = None
        if hr and dk:
            hr_edge = hr["over_odds"] - dk["over_odds"]

        signals[(name_lower, line)] = {
            "player_name": entries[0]["player_name"],
            "line": line,
            "open_odds": open_odds,
            "close_odds": close_odds,
            "move": move,
            "signal": signal,
            "books": books,
            "best_book": best_book,
            "best_odds": best_odds,
            "hr_edge": hr_edge,
        }

    log.info(
        f"Steam signals for {target_date}: {len(signals)} lines, "
        f"{sum(1 for s in signals.values() if 'steam' in s['signal'])} steaming, "
        f"{sum(1 for s in signals.values() if 'fade' in s['signal'])} fading"
    )
    return signals


def annotate_picks(picks: list[dict], signals: dict) -> list[dict]:
    """Annotate a list of picks with steam detector signals.

    Adds to each pick dict:
        steam_signal: str — "strong_steam", "mild_steam", "neutral", etc.
        steam_move: int — line movement in cents
        steam_emoji: str — 🔥🔥, 🔥, ➡️, ⚠️, 🚫
        best_book: str — book with best odds
        best_odds: int — best available odds
        hr_edge: int — Hard Rock edge vs DraftKings

    Match is by player name (fuzzy) + line value.
    """
    for pick in picks:
        player = pick.get("player", "").lower().strip()
        line = pick.get("line", 0.5)

        # Try exact match first
        sig = signals.get((player, line))

        # Fuzzy: try last name match
        if sig is None:
            last_name = player.split()[-1] if player else ""
            for (sname, sline), s in signals.items():
                if sline == line and sname.split()[-1] == last_name:
                    sig = s
                    break

        if sig:
            pick["steam_signal"] = sig["signal"]
            pick["steam_move"] = sig["move"]
            pick["best_book_bp"] = sig["best_book"]
            pick["best_odds_bp"] = sig["best_odds"]
            pick["hr_edge"] = sig["hr_edge"]

            # Emoji for display
            signal = sig["signal"]
            if signal == "strong_steam":
                pick["steam_emoji"] = "🔥🔥"
            elif signal == "mild_steam":
                pick["steam_emoji"] = "🔥"
            elif signal == "strong_fade":
                pick["steam_emoji"] = "🚫"
            elif signal == "mild_fade":
                pick["steam_emoji"] = "⚠️"
            else:
                pick["steam_emoji"] = "➡️"
        else:
            pick["steam_signal"] = "no_data"
            pick["steam_move"] = 0
            pick["steam_emoji"] = "❓"
            pick["best_book_bp"] = None
            pick["best_odds_bp"] = None
            pick["hr_edge"] = None

    return picks


def filter_picks_by_steam(
    picks: list[dict],
    block_strong_fade: bool = True,
    boost_strong_steam: bool = True,
) -> list[dict]:
    """Filter/adjust picks based on steam signals.

    - block_strong_fade: Remove picks where line moved 20+ cents AWAY
      from our side (36% hit rate = coin flip minus)
    - boost_strong_steam: Increase unit size by 50% for strong steam picks
      (55.7% hit rate)

    Returns filtered list. Blocked picks are logged.
    """
    filtered = []
    blocked = []

    for pick in picks:
        signal = pick.get("steam_signal", "no_data")

        if block_strong_fade and signal == "strong_fade":
            blocked.append(pick)
            continue

        if boost_strong_steam and signal == "strong_steam":
            # Boost by 50% (capped later by max risk)
            old_dollars = pick.get("dollars", 0)
            old_units = pick.get("units", 0)
            pick["dollars"] = round(old_dollars * 1.5, 2)
            pick["units"] = round(old_units * 1.5, 1)
            pick["steam_boosted"] = True

        filtered.append(pick)

    if blocked:
        names = [p.get("player", "?") for p in blocked]
        log.info(f"Steam filter blocked {len(blocked)} picks (strong fade): {', '.join(names)}")

    return filtered


def print_steam_report(picks: list[dict]):
    """Print a steam summary for the daily picks."""
    if not picks:
        return

    print("\n" + "=" * 70)
    print("STEAM DETECTOR REPORT")
    print("=" * 70)

    for pick in sorted(picks, key=lambda p: p.get("steam_move", 0)):
        player = pick.get("player", "?")
        emoji = pick.get("steam_emoji", "?")
        move = pick.get("steam_move", 0)
        hr_edge = pick.get("hr_edge")
        best_book = pick.get("best_book_bp", "?")
        best_odds = pick.get("best_odds_bp")
        boosted = pick.get("steam_boosted", False)

        parts = [f"  {emoji} {player}"]
        if move != 0:
            parts.append(f"move: {move:+d}¢")
        if hr_edge and hr_edge > 0:
            parts.append(f"HR edge: +{hr_edge}¢")
        if best_book and best_odds is not None:
            odds_str = f"+{best_odds}" if best_odds > 0 else str(best_odds)
            parts.append(f"best: {best_book} {odds_str}")
        if boosted:
            parts.append("⬆️ BOOSTED")

        print(" | ".join(parts))

    # Summary
    strong = sum(1 for p in picks if p.get("steam_signal") == "strong_steam")
    mild = sum(1 for p in picks if p.get("steam_signal") == "mild_steam")
    fades = sum(1 for p in picks if "fade" in p.get("steam_signal", ""))
    print(f"\n  Summary: {strong} strong steam, {mild} mild steam, {fades} fading")
