
#!/usr/bin/env python3
"""Strategy #2 deploy-rule builder with no-vig robustness checks.

Builds candidate rules at (market, side, line, odds_bucket) that are:
- profitable in train and holdout
- positive edge vs no-vig fair probability in train and holdout
- adequately sampled in both periods
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


def american_to_implied_prob(odds: pd.Series) -> pd.Series:
    odds = pd.to_numeric(odds, errors="coerce")
    out = pd.Series(np.nan, index=odds.index, dtype="float64")
    neg_mask = odds < 0
    pos_mask = odds > 0
    out.loc[neg_mask] = (-odds.loc[neg_mask]) / ((-odds.loc[neg_mask]) + 100)
    out.loc[pos_mask] = 100 / (odds.loc[pos_mask] + 100)
    return out


def american_profit_per_unit_stake(odds: pd.Series) -> pd.Series:
    odds = pd.to_numeric(odds, errors="coerce")
    out = pd.Series(np.nan, index=odds.index, dtype="float64")
    neg_mask = odds < 0
    pos_mask = odds > 0
    out.loc[neg_mask] = 100 / (-odds.loc[neg_mask])
    out.loc[pos_mask] = odds.loc[pos_mask] / 100
    return out


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

    metric_map = {"goals": "goals", "assists": "assists", "points": "points", "sog": "shots"}
    df["actual"] = df.apply(lambda r: r[metric_map[r["market"]]], axis=1)

    return df[df["actual"].notna()].copy()


def explode_sides(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["market", "player_name", "event_date", "line", "actual", "over_odds", "under_odds"]].copy()

    base["p_over_imp"] = american_to_implied_prob(base["over_odds"])
    base["p_under_imp"] = american_to_implied_prob(base["under_odds"])
    vig = base["p_over_imp"] + base["p_under_imp"]
    base["p_over_fair"] = base["p_over_imp"] / vig
    base["p_under_fair"] = base["p_under_imp"] / vig

    over = base.copy()
    over["side"] = "over"
    over["odds"] = over["over_odds"]
    over["win"] = over["actual"] > over["line"]
    over["push"] = over["actual"] == over["line"]
    over["fair_prob"] = over["p_over_fair"]

    under = base.copy()
    under["side"] = "under"
    under["odds"] = under["under_odds"]
    under["win"] = under["actual"] < under["line"]
    under["push"] = under["actual"] == under["line"]
    under["fair_prob"] = under["p_under_fair"]

    bets = pd.concat([over, under], ignore_index=True)
    bets = bets[~bets["push"]].copy()

    bets["profit_if_win"] = american_profit_per_unit_stake(bets["odds"])
    bets = bets[bets["profit_if_win"].notna() & bets["fair_prob"].notna()].copy()

    bets["profit_units"] = np.where(bets["win"], bets["profit_if_win"], -1.0)
    bets["win_f"] = bets["win"].astype(float)
    bets["event_dt"] = pd.to_datetime(bets["event_date"])

    return assign_odds_bucket(bets)


def summarize(df: pd.DataFrame, keys: list[str], prefix: str) -> pd.DataFrame:
    g = df.groupby(keys, as_index=False).agg(
        bets=("win", "size"),
        wins=("win", "sum"),
        win_rate=("win_f", "mean"),
        roi=("profit_units", "mean"),
        units=("profit_units", "sum"),
        avg_fair_prob=("fair_prob", "mean"),
        avg_odds=("odds", "mean"),
    )
    g["edge_vs_fair"] = g["win_rate"] - g["avg_fair_prob"]
    return g.rename(columns={
        "bets": f"{prefix}_bets",
        "wins": f"{prefix}_wins",
        "win_rate": f"{prefix}_win_rate",
        "roi": f"{prefix}_roi",
        "units": f"{prefix}_units",
        "avg_fair_prob": f"{prefix}_avg_fair_prob",
        "avg_odds": f"{prefix}_avg_odds",
        "edge_vs_fair": f"{prefix}_edge_vs_fair",
    })


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy #2 deploy-rule builder")
    parser.add_argument("--start-date", default="2022-10-07")
    parser.add_argument("--end-date", default="2024-04-04")
    parser.add_argument("--split-date", default="2023-09-30", help="Train <= split, test > split")
    parser.add_argument("--best-only", action="store_true", help="Use only rows with is_best=true")
    parser.add_argument("--min-train-bets", type=int, default=300)
    parser.add_argument("--min-test-bets", type=int, default=150)
    parser.add_argument("--min-train-edge", type=float, default=0.01)
    parser.add_argument("--min-test-edge", type=float, default=0.005)
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    joined = load_joined_data(args.start_date, args.end_date, args.best_only)
    bets = explode_sides(joined)

    split_dt = pd.to_datetime(args.split_date)
    train = bets[bets["event_dt"] <= split_dt].copy()
    test = bets[bets["event_dt"] > split_dt].copy()

    train_rule = summarize(train, ["market", "side", "line", "odds_bucket"], "train")
    test_rule = summarize(test, ["market", "side", "line", "odds_bucket"], "test")

    merged = train_rule.merge(test_rule, on=["market", "side", "line", "odds_bucket"], how="inner")
    merged["roi_delta"] = merged["test_roi"] - merged["train_roi"]

    deploy = merged[
        (merged["train_bets"] >= args.min_train_bets)
        & (merged["test_bets"] >= args.min_test_bets)
        & (merged["train_roi"] > 0)
        & (merged["test_roi"] > 0)
        & (merged["train_edge_vs_fair"] >= args.min_train_edge)
        & (merged["test_edge_vs_fair"] >= args.min_test_edge)
    ].copy()
    deploy = deploy.sort_values(["test_roi", "test_bets"], ascending=[False, False])

    suffix = "best_only" if args.best_only else "all_books"
    out_path = OUT_DIR / f"strategy2_deploy_candidates_{suffix}.csv"
    all_path = OUT_DIR / f"strategy2_deploy_candidates_all_rules_{suffix}.csv"

    deploy.to_csv(out_path, index=False)
    merged.sort_values(["test_roi", "test_bets"], ascending=[False, False]).to_csv(all_path, index=False)

    print("=== Strategy #2 Deploy Rules (No-vig robustness) ===")
    print(f"Universe: {'is_best=true only' if args.best_only else 'all books'}")
    print(f"Joined rows: {len(joined):,} | Bet rows: {len(bets):,}")
    print(f"Train rows: {len(train):,} | Test rows: {len(test):,}")
    print(f"Candidates: {len(deploy):,}")

    if deploy.empty:
        print("\nNo candidates passed filters.")
    else:
        cols = [
            "market",
            "side",
            "line",
            "odds_bucket",
            "train_bets",
            "train_roi",
            "train_edge_vs_fair",
            "test_bets",
            "test_roi",
            "test_edge_vs_fair",
            "roi_delta",
        ]
        print("\nTop deploy candidates:")
        print(deploy[cols].head(20).to_string(index=False))

    print(f"\nSaved: {out_path}")
    print(f"Saved: {all_path}")


if __name__ == "__main__":
    main()
