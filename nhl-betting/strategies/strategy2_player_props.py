
#!/usr/bin/env python3
"""Strategy #2 research on player prop odds (goals/assists/points/SOG).

Uses real historical player_odds data + player_stats outcomes and reports:
1) Market inefficiencies (market/side hit rates + ROI)
2) Line value (market/side/line buckets)
3) Player-level edges
4) Seasonal patterns (early/mid/late season)

ROI assumes flat -110 pricing as requested:
- Win: +0.9091 units
- Loss: -1.0 units
- Push: 0 units (excluded from bet counts/ROI)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse

import numpy as np
import pandas as pd

from lib.db import get_conn

BRIDGE_PATH = Path(__file__).resolve().parent.parent / "model" / "player_odds_bridge.csv"
OUT_DIR = Path(__file__).resolve().parent / "output"

WIN_UNITS = 100 / 110  # +0.9091
LOSS_UNITS = -1.0


def american_to_implied_prob(odds: pd.Series) -> pd.Series:
    odds = pd.to_numeric(odds, errors="coerce")
    out = pd.Series(np.nan, index=odds.index, dtype="float64")
    neg_mask = odds < 0
    pos_mask = odds > 0
    out.loc[neg_mask] = (-odds.loc[neg_mask]) / ((-odds.loc[neg_mask]) + 100)
    out.loc[pos_mask] = 100 / (odds.loc[pos_mask] + 100)
    return out


def get_data(start_date: str, end_date: str, best_only: bool) -> pd.DataFrame:
    best_filter = "AND o.is_best = true" if best_only else ""

    odds_sql = f"""
        SELECT
            o.id,
            o.market,
            o.bp_player_id,
            o.player_name,
            o.event_date,
            o.line,
            o.over_odds,
            o.under_odds,
            o.is_best
        FROM player_odds o
        WHERE o.event_date BETWEEN %s AND %s
          {best_filter}
    """

    stats_sql = """
        SELECT
            ps.player_id,
            g.game_date AS event_date,
            ps.goals,
            ps.assists,
            ps.points,
            ps.shots
        FROM player_stats ps
        JOIN games g ON g.game_id = ps.game_id
        WHERE g.game_date BETWEEN %s AND %s
    """

    with get_conn(db="nhl_betting") as conn:
        odds = pd.read_sql_query(odds_sql, conn, params=(start_date, end_date))
        stats = pd.read_sql_query(stats_sql, conn, params=(start_date, end_date))

    bridge = pd.read_csv(BRIDGE_PATH)[["bp_player_id", "player_id"]].drop_duplicates()
    stats = stats.groupby(["player_id", "event_date"], as_index=False).first()

    df = odds.merge(bridge, on="bp_player_id", how="left")
    df = df.merge(stats, on=["player_id", "event_date"], how="left")

    metric_map = {
        "goals": "goals",
        "assists": "assists",
        "points": "points",
        "sog": "shots",
    }
    df["actual"] = df.apply(lambda r: r[metric_map[r["market"]]], axis=1)

    # Keep only rows with known outcomes
    return df[df["actual"].notna()].copy()


def explode_sides(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["market", "player_name", "event_date", "line", "actual", "over_odds", "under_odds"]].copy()

    over = base.copy()
    over["side"] = "over"
    over["win"] = over["actual"] > over["line"]
    over["push"] = over["actual"] == over["line"]
    over["odds"] = over["over_odds"]

    under = base.copy()
    under["side"] = "under"
    under["win"] = under["actual"] < under["line"]
    under["push"] = under["actual"] == under["line"]
    under["odds"] = under["under_odds"]

    bets = pd.concat([over, under], ignore_index=True)
    bets["implied_prob"] = american_to_implied_prob(bets["odds"])

    # Remove pushes for ROI / win-rate accounting
    bets = bets[~bets["push"]].copy()
    bets["profit_units"] = np.where(bets["win"], WIN_UNITS, LOSS_UNITS)

    d = pd.to_datetime(bets["event_date"])
    bets["month"] = d.dt.month
    bets["season"] = np.where(d.dt.month >= 9, d.dt.year, d.dt.year - 1).astype(str) + "-" + (
        np.where(d.dt.month >= 9, d.dt.year + 1, d.dt.year).astype(str)
    )
    bets["season_phase"] = np.select(
        [bets["month"].isin([10, 11, 12]), bets["month"].isin([1, 2]), bets["month"].isin([3, 4])],
        ["early", "mid", "late"],
        default="other",
    )

    return bets


def summarize(grouped: pd.core.groupby.generic.DataFrameGroupBy) -> pd.DataFrame:
    out = grouped.agg(
        bets=("win", "size"),
        wins=("win", "sum"),
        win_rate=("win", "mean"),
        roi=("profit_units", "mean"),
        profit_units=("profit_units", "sum"),
        avg_implied=("implied_prob", "mean"),
    ).reset_index()
    out["edge_vs_implied"] = out["win_rate"] - out["avg_implied"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest Strategy #2 on player_odds")
    parser.add_argument("--start-date", default="2022-10-07")
    parser.add_argument("--end-date", default="2024-04-04")
    parser.add_argument("--best-only", action="store_true", help="Use only rows where is_best=true")
    parser.add_argument("--min-line-bets", type=int, default=150)
    parser.add_argument("--min-player-bets", type=int, default=40)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    joined = get_data(args.start_date, args.end_date, best_only=args.best_only)
    bets = explode_sides(joined)

    market_summary = summarize(bets.groupby(["market", "side"]))
    line_summary = summarize(bets.groupby(["market", "side", "line"]))
    player_summary = summarize(bets.groupby(["market", "player_name", "side"]))
    season_summary = summarize(bets.groupby(["season", "market", "side"]))
    phase_summary = summarize(bets[bets["season_phase"] != "other"].groupby(["market", "side", "season_phase"]))

    line_summary_filtered = line_summary[line_summary["bets"] >= args.min_line_bets].copy()
    player_summary_filtered = player_summary[player_summary["bets"] >= args.min_player_bets].copy()

    suffix = "best_only" if args.best_only else "all_books"
    market_summary.to_csv(OUT_DIR / f"strategy2_market_summary_{suffix}.csv", index=False)
    line_summary_filtered.sort_values("roi", ascending=False).to_csv(
        OUT_DIR / f"strategy2_line_summary_{suffix}.csv", index=False
    )
    player_summary_filtered.sort_values("roi", ascending=False).to_csv(
        OUT_DIR / f"strategy2_player_summary_{suffix}.csv", index=False
    )
    season_summary.sort_values(["season", "roi"], ascending=[True, False]).to_csv(
        OUT_DIR / f"strategy2_season_summary_{suffix}.csv", index=False
    )
    phase_summary.sort_values("roi", ascending=False).to_csv(
        OUT_DIR / f"strategy2_phase_summary_{suffix}.csv", index=False
    )

    print("=== Strategy #2 Backtest Complete ===")
    print(f"Date range: {args.start_date} -> {args.end_date}")
    print(f"Universe: {'is_best=true only' if args.best_only else 'all books'}")
    print(f"Rows with outcomes: {len(joined):,}")
    print(f"Bet records after side expansion (no pushes): {len(bets):,}")

    print("\nTop market/side edges by ROI (-110 assumption):")
    print(market_summary.sort_values("roi", ascending=False).head(8).to_string(index=False))

    print("\nTop line buckets (filtered):")
    print(line_summary_filtered.sort_values("roi", ascending=False).head(10).to_string(index=False))

    print("\nTop player-level edges (filtered):")
    print(player_summary_filtered.sort_values("roi", ascending=False).head(15).to_string(index=False))

    print(f"\nOutput saved to: {OUT_DIR}")


if __name__ == "__main__":
    main()
