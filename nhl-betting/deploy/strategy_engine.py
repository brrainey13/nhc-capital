#!/usr/bin/env python3
"""
Strategy engine for NHL goalie saves betting.
Loads daily slate, applies all 5 strategy filters, outputs picks.
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from kelly_sizer import estimate_win_prob, size_bet

ROOT = Path(__file__).parent.parent
DEPLOY_DIR = Path(__file__).parent
PICKS_DIR = ROOT / "picks"
PICKS_DIR.mkdir(exist_ok=True)
DATA_DIR = ROOT / "data"

with open(DEPLOY_DIR / "config.yaml") as f:
    CONFIG = yaml.safe_load(f)

logger = logging.getLogger("strategy_engine")


def apply_mandatory_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Apply filters that disqualify bets regardless of strategy."""
    min_juice = CONFIG["betting"]["min_juice"]
    blacklist = CONFIG.get("blacklist_teams", [])

    before = len(df)
    filtered = df.copy()

    # 1. Skip if juice worse than -115
    filtered["relevant_odds"] = np.where(
        filtered["model_side"] == "under",
        filtered["under_odds"],
        filtered["over_odds"],
    )
    filtered = filtered[filtered["relevant_odds"] >= min_juice]
    logger.info(f"  Juice filter (>= {min_juice}): {before} → {len(filtered)}")

    # 2. Skip if starter not confirmed by pick time
    not_confirmed = filtered[~filtered["starter_confirmed"]]
    if len(not_confirmed) > 0:
        logger.warning(f"  ⚠️ {len(not_confirmed)} goalies not yet confirmed — keeping but flagging")

    # 3. Blacklist: skip if opponent in blacklist AND Corsi < 30th percentile
    if blacklist:
        blacklist_mask = (
            filtered["away_team"].isin(blacklist) | filtered["home_team"].isin(blacklist)
        )
        # Determine opponent abbreviation
        opp_team = np.where(filtered["is_home"] == 1, filtered["away_team"], filtered["home_team"])
        opp_in_blacklist = pd.Series(opp_team).isin(blacklist).values
        low_corsi = filtered["opp_corsi_pct_avg_10"] < filtered["corsi_q30"]
        exclude = opp_in_blacklist & low_corsi
        n_excluded = exclude.sum()
        if n_excluded > 0:
            logger.info(f"  Blacklist filter: removing {n_excluded} (elite teams w/ low Corsi)")
        filtered = filtered[~exclude]

    return filtered


def run_mf3a(df: pd.DataFrame) -> pd.DataFrame:
    """MF3a: gap ∈ [1.0, 1.5), opponent Corsi bottom 25%, UNDER."""
    picks = df[
        (df["model_side"] == "under")
        & (df["abs_gap"] >= 1.0)
        & (df["abs_gap"] < 1.5)
        & (df["opp_corsi_pct_avg_10"] < df["corsi_q25"])
    ].copy()
    picks["strategy"] = "MF3a"
    picks["confidence"] = "HIGH"
    return picks


def run_mf3b(df: pd.DataFrame) -> pd.DataFrame:
    """MF3b: gap ≥ 2.5, opponent Corsi bottom 25%, UNDER."""
    picks = df[
        (df["model_side"] == "under")
        & (df["abs_gap"] >= 2.5)
        & (df["opp_corsi_pct_avg_10"] < df["corsi_q25"])
    ].copy()
    picks["strategy"] = "MF3b"
    picks["confidence"] = "HIGH"
    return picks


def run_mf5(df: pd.DataFrame) -> pd.DataFrame:
    """MF5: gap ≥ 1.0, opponent Corsi bottom 30%, UNDER."""
    picks = df[
        (df["model_side"] == "under")
        & (df["abs_gap"] >= 1.0)
        & (df["opp_corsi_pct_avg_10"] < df["corsi_q30"])
    ].copy()
    picks["strategy"] = "MF5"
    picks["confidence"] = "MEDIUM"
    return picks


def run_mf2(df: pd.DataFrame) -> pd.DataFrame:
    """MF2: gap ≥ 2.0, B2B (days_rest ≤ 1), UNDER."""
    picks = df[
        (df["model_side"] == "under")
        & (df["abs_gap"] >= 2.0)
        & (df["days_rest"] <= 1)
    ].copy()
    picks["strategy"] = "MF2"
    picks["confidence"] = "HIGH"
    return picks


def run_pf1(df: pd.DataFrame) -> pd.DataFrame:
    """PF1: opponent Corsi top 25% on all 3 metrics, OVER. Paper only."""
    picks = df[
        (df["opp_corsi_pct_avg_10"] > df["corsi_q75"])
        & (df["opp_corsi_diff_avg_10"] > df["corsi_diff_q75"])
        & (df["opp_puck_control_avg_10"] > df["puck_control_q75"])
    ].copy()
    picks["strategy"] = "PF1"
    picks["confidence"] = "LOW"
    picks["model_side"] = "over"  # PF1 is always OVER
    return picks


def resolve_overlaps(all_picks: pd.DataFrame) -> pd.DataFrame:
    """
    When MF5 and MF3a/MF3b fire on the same goalie, keep the tighter filter.
    Priority: MF3a > MF3b > MF2 > MF5 > PF1
    """
    priority = {"MF3a": 1, "MF3b": 2, "MF2": 3, "MF5": 4, "PF1": 5}

    if all_picks.empty:
        return all_picks

    all_picks["priority"] = all_picks["strategy"].map(priority)
    resolved = all_picks.sort_values("priority").drop_duplicates(subset=["player_name"], keep="first")
    resolved = resolved.drop(columns=["priority"])

    n_removed = len(all_picks) - len(resolved)
    if n_removed > 0:
        logger.info(f"  Overlap resolution: {len(all_picks)} → {len(resolved)} picks")

    return resolved


def format_picks(picks_df: pd.DataFrame, date: str) -> dict:
    """Format picks into the output JSON structure."""
    bankroll = CONFIG["betting"]["bankroll"]
    kelly_frac = CONFIG["betting"]["kelly_fraction"]

    picks_list = []
    for _, row in picks_df.iterrows():
        strategy = row["strategy"]
        gap = row["abs_gap"]
        side = row["model_side"]
        odds = int(row["under_odds"] if side == "under" else row["over_odds"])

        # Win probability estimate
        win_prob = estimate_win_prob(strategy, gap)

        # Kelly sizing
        sizing = size_bet(win_prob, odds, bankroll=bankroll, kelly_frac=kelly_frac)

        game_str = f"{row['away_team']} @ {row['home_team']}"

        # Build reasoning
        reasons = []
        reasons.append(f"Gap {gap:.1f}")
        if "corsi" in strategy.lower() or strategy.startswith("MF3") or strategy == "MF5":
            corsi_pct = row.get("opp_corsi_pct_avg_10")
            if corsi_pct is not None:
                # Calculate opponent's Corsi percentile vs our training data
                q25 = row.get("corsi_q25", 0.475)
                if corsi_pct < q25:
                    reasons.append(f"opponent bottom 25% Corsi ({corsi_pct:.3f})")
        if strategy == "MF2":
            reasons.append(f"B2B (rest={row['days_rest']}d)")
        if strategy == "PF1":
            reasons.append("triple Corsi top 25%")
        if row["is_home"] == 0:
            reasons.append("away game")

        pick = {
            "game": game_str,
            "goalie": row["player_name"],
            "line": float(row["line"]),
            "juice": odds,
            "strategy": strategy,
            "bet": side.upper(),
            "confidence": row["confidence"],
            "model_gap": round(gap, 1),
            "model_prediction": round(row["pred_saves"], 1),
            "opponent_corsi_pct": round(row.get("opp_corsi_pct_avg_10", 0), 3),
            "bet_size_025kelly": f"${sizing['bet_amount']:.0f}",
            "bet_size_050kelly": f"${sizing['bet_amount'] * 2:.0f}",
            "estimated_win_prob": f"{win_prob:.1%}",
            "expected_value": f"{sizing['expected_value']:+.4f}",
            "starter_confirmed": bool(row.get("starter_confirmed", False)),
            "reasoning": ", ".join(reasons),
            "paper_only": strategy in CONFIG["strategies"].get("paper_only", []),
        }

        picks_list.append(pick)

    # Sort by confidence then gap
    conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    picks_list.sort(key=lambda x: (conf_order.get(x["confidence"], 3), -x["model_gap"]))

    return {
        "date": date,
        "generated_at": datetime.now().isoformat(),
        "paper_trading": CONFIG["strategies"]["paper_trading"],
        "bankroll": bankroll,
        "kelly_fraction": kelly_frac,
        "n_picks": len(picks_list),
        "total_action": f"${sum(float(p['bet_size_025kelly'].replace('$', '')) for p in picks_list):.0f}",
        "picks": picks_list,
    }


def run_strategies(date: str = None) -> dict:
    """Run all strategies on today's daily slate."""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"\n{'='*60}")
    logger.info(f"STRATEGY ENGINE — {date}")
    logger.info(f"{'='*60}")

    # Load daily slate
    slate_path = DATA_DIR / f"daily_slate_{date}.csv"
    if not slate_path.exists():
        logger.error(f"No daily slate found at {slate_path}")
        logger.error("Run data_pipeline.py first!")
        return {"date": date, "picks": [], "error": "No slate"}

    df = pd.read_csv(slate_path)
    logger.info(f"  Loaded {len(df)} goalies from slate")

    if df.empty:
        return {"date": date, "picks": []}

    # Apply mandatory filters
    df = apply_mandatory_filters(df)
    if df.empty:
        logger.info("  All goalies filtered out by mandatory filters")
        return {"date": date, "picks": []}

    # Run each enabled strategy
    enabled = CONFIG["strategies"]["enabled"] + CONFIG["strategies"].get("paper_only", [])
    all_picks = []

    strategy_runners = {
        "MF3a": run_mf3a,
        "MF3b": run_mf3b,
        "MF5": run_mf5,
        "MF2": run_mf2,
        "PF1": run_pf1,
    }

    for strat_name in enabled:
        runner = strategy_runners.get(strat_name)
        if runner:
            picks = runner(df)
            logger.info(f"  {strat_name}: {len(picks)} picks")
            if not picks.empty:
                all_picks.append(picks)

    if not all_picks:
        logger.info("  No picks today")
        return {"date": date, "picks": []}

    combined = pd.concat(all_picks, ignore_index=True)
    resolved = resolve_overlaps(combined)

    logger.info(f"  Final picks: {len(resolved)}")

    # Format output
    output = format_picks(resolved, date)

    # Save
    picks_path = PICKS_DIR / f"picks_{date}.json"
    with open(picks_path, "w") as f:
        json.dump(output, f, indent=2)
    logger.info(f"  Saved to {picks_path}")

    return output


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    date = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_strategies(date)

    print(f"\n{json.dumps(result, indent=2)}")
