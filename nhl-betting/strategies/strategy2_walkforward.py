
#!/usr/bin/env python3
"""Strategy #2 walk-forward validation using REAL historical odds.

Goal:
- Use 2022-23 as train and 2023-24 as holdout test.
- Validate whether train-discovered edges survive out-of-sample.

Data:
- player_odds (market, line, over_odds, under_odds, is_best)
- player_stats outcomes via model/player_odds_bridge.csv

Outputs:
- strategies/output/strategy2_walkforward_line_candidates.csv
- strategies/output/strategy2_walkforward_market_summary.csv
- strategies/output/strategy2_walkforward_price_regimes.csv
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


def american_profit_per_unit_stake(odds: pd.Series) -> pd.Series:
    odds = pd.to_numeric(odds, errors="coerce")
    out = pd.Series(np.nan, index=odds.index, dtype="float64")
    neg_mask = odds < 0
    pos_mask = odds > 0
    out.loc[neg_mask] = 100 / (-odds.loc[neg_mask])
    out.loc[pos_mask] = odds.loc[pos_mask] / 100
    return out


def american_to_implied_prob(odds: pd.Series) -> pd.Series:
    odds = pd.to_numeric(odds, errors="coerce")
    out = pd.Series(np.nan, index=odds.index, dtype="float64")
    neg_mask = odds < 0
    pos_mask = odds > 0
    out.loc[neg_mask] = (-odds.loc[neg_mask]) / ((-odds.loc[neg_mask]) + 100)
    out.loc[pos_mask] = 100 / (odds.loc[pos_mask] + 100)
    return out


def load_joined_data(start_date: str, end_date: str, best_only: bool) -> pd.DataFrame:
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
          AND o.market IN ('goals', 'assists', 'points', 'sog')
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

    return df[df["actual"].notna()].copy()


def explode_sides(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["market", "player_name", "event_date", "line", "actual", "over_odds", "under_odds"]].copy()

    over = base.copy()
    over["side"] = "over"
    over["odds"] = over["over_odds"]
    over["win"] = over["actual"] > over["line"]
    over["push"] = over["actual"] == over["line"]

    under = base.copy()
    under["side"] = "under"
    under["odds"] = under["under_odds"]
    under["win"] = under["actual"] < under["line"]
    under["push"] = under["actual"] == under["line"]

    bets = pd.concat([over, under], ignore_index=True)
    bets = bets[~bets["push"]].copy()

    bets["profit_if_win"] = american_profit_per_unit_stake(bets["odds"])
    bets = bets[bets["profit_if_win"].notna()].copy()

    bets["profit_units"] = np.where(bets["win"], bets["profit_if_win"], -1.0)
    bets["implied_prob"] = american_to_implied_prob(bets["odds"])

    bets["event_dt"] = pd.to_datetime(bets["event_date"])
    return bets


def summarize(df: pd.DataFrame, keys: list[str], prefix: str) -> pd.DataFrame:
    g = df.groupby(keys, as_index=False).agg(
        bets=("win", "size"),
        wins=("win", "sum"),
        win_rate=("win", "mean"),
        roi=("profit_units", "mean"),
        units=("profit_units", "sum"),
        avg_implied=("implied_prob", "mean"),
        avg_odds=("odds", "mean"),
    )
    g["edge_vs_implied"] = g["win_rate"] - g["avg_implied"]
    return g.rename(columns={
        "bets": f"{prefix}_bets",
        "wins": f"{prefix}_wins",
        "win_rate": f"{prefix}_win_rate",
        "roi": f"{prefix}_roi",
        "units": f"{prefix}_units",
        "avg_implied": f"{prefix}_avg_implied",
        "avg_odds": f"{prefix}_avg_odds",
        "edge_vs_implied": f"{prefix}_edge_vs_implied",
    })


def assign_odds_bucket(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["odds_bucket"] = pd.cut(
        out["odds"],
        bins=[-1000, -200, -160, -130, -110, -100, 110, 150, 1000],
        right=False,
        include_lowest=True,
    )
    out["odds_bucket"] = out["odds_bucket"].astype(str)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy #2 walk-forward validation")
    parser.add_argument("--start-date", default="2022-10-07")
    parser.add_argument("--end-date", default="2024-04-04")
    parser.add_argument("--split-date", default="2023-09-30", help="Train <= split, test > split")
    parser.add_argument("--best-only", action="store_true", help="Use only rows with is_best=true")
    parser.add_argument("--min-train-bets", type=int, default=200)
    parser.add_argument("--min-test-bets", type=int, default=100)
    parser.add_argument("--min-regime-train-bets", type=int, default=300)
    parser.add_argument("--min-regime-test-bets", type=int, default=150)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    joined = load_joined_data(args.start_date, args.end_date, args.best_only)
    bets = explode_sides(joined)

    split_dt = pd.to_datetime(args.split_date)
    train = bets[bets["event_dt"] <= split_dt].copy()
    test = bets[bets["event_dt"] > split_dt].copy()
    train = assign_odds_bucket(train)
    test = assign_odds_bucket(test)

    # Market-level stability check
    train_market = summarize(train, ["market", "side"], "train")
    test_market = summarize(test, ["market", "side"], "test")
    market = train_market.merge(test_market, on=["market", "side"], how="inner")
    market["roi_delta"] = market["test_roi"] - market["train_roi"]
    market = market.sort_values("test_roi", ascending=False)

    # Candidate selection from training period (line-level)
    train_line = summarize(train, ["market", "side", "line"], "train")
    test_line = summarize(test, ["market", "side", "line"], "test")

    candidates = train_line[
        (train_line["train_bets"] >= args.min_train_bets)
        & (train_line["train_roi"] > 0)
        & (train_line["train_edge_vs_implied"] > 0)
    ].copy()

    wf = candidates.merge(test_line, on=["market", "side", "line"], how="left")
    wf = wf[wf["test_bets"].fillna(0) >= args.min_test_bets].copy()
    wf["roi_delta"] = wf["test_roi"] - wf["train_roi"]
    wf = wf.sort_values(["test_roi", "test_bets"], ascending=[False, False])

    # Price-regime robustness: only keep odds buckets that were positive in train.
    train_regime = summarize(train, ["market", "side", "line", "odds_bucket"], "train")
    test_regime = summarize(test, ["market", "side", "line", "odds_bucket"], "test")

    regime_candidates = train_regime[
        (train_regime["train_bets"] >= args.min_regime_train_bets)
        & (train_regime["train_roi"] > 0)
        & (train_regime["train_edge_vs_implied"] > 0)
    ].copy()
    regime_wf = regime_candidates.merge(test_regime, on=["market", "side", "line", "odds_bucket"], how="left")
    regime_wf = regime_wf[regime_wf["test_bets"].fillna(0) >= args.min_regime_test_bets].copy()
    regime_wf["roi_delta"] = regime_wf["test_roi"] - regime_wf["train_roi"]
    regime_wf = regime_wf.sort_values(["test_roi", "test_bets"], ascending=[False, False])

    suffix = "best_only" if args.best_only else "all_books"
    market_path = OUT_DIR / f"strategy2_walkforward_market_summary_{suffix}.csv"
    line_path = OUT_DIR / f"strategy2_walkforward_line_candidates_{suffix}.csv"
    regime_path = OUT_DIR / f"strategy2_walkforward_price_regimes_{suffix}.csv"

    market.to_csv(market_path, index=False)
    wf.to_csv(line_path, index=False)
    regime_wf.to_csv(regime_path, index=False)

    print("=== Strategy #2 Walk-Forward Complete (real odds) ===")
    print(f"Date range: {args.start_date} -> {args.end_date}")
    print(f"Split date: {args.split_date} (train<=split, test>split)")
    print(f"Universe: {'is_best=true only' if args.best_only else 'all books'}")
    print(f"Joined rows: {len(joined):,}")
    print(f"Bet rows (no pushes): {len(bets):,}")
    print(f"Train rows: {len(train):,} | Test rows: {len(test):,}")

    print("\nTop market/side on holdout by ROI:")
    print(market[["market", "side", "train_bets", "train_roi", "test_bets", "test_roi", "roi_delta"]].head(10).to_string(index=False))

    if wf.empty:
        print("\nNo line-level candidates met min train/test filters.")
    else:
        print("\nLine-level candidates surviving holdout:")
        print(
            wf[
                [
                    "market",
                    "side",
                    "line",
                    "train_bets",
                    "train_roi",
                    "test_bets",
                    "test_roi",
                    "roi_delta",
                ]
            ]
            .head(15)
            .to_string(index=False)
        )

    if regime_wf.empty:
        print("\nNo price-regime candidates met min train/test filters.")
    else:
        print("\nPrice-regime candidates surviving holdout:")
        print(
            regime_wf[
                [
                    "market",
                    "side",
                    "line",
                    "odds_bucket",
                    "train_bets",
                    "train_roi",
                    "test_bets",
                    "test_roi",
                    "roi_delta",
                ]
            ]
            .head(15)
            .to_string(index=False)
        )

    print(f"\nSaved: {market_path}")
    print(f"Saved: {line_path}")
    print(f"Saved: {regime_path}")


if __name__ == "__main__":
    main()
