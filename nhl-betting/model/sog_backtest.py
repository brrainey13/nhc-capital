"""
Full SOG model backtest.
- Separate F/D models
- Walk-forward: train on all seasons except last, test on held-out season
- Kelly sizing, cumulative P&L, breakdowns by line/position/team/edge/direction
- Outputs: DB table, summary markdown, P&L chart
"""

import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import psycopg2
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

DB = "postgresql://connorrainey@localhost:5432/nhl_betting"
EDGE_THRESHOLD = 0.75
UNIT_SIZE = 100  # dollars
KELLY_FRACTION = 0.25  # quarter-Kelly
VIG_ODDS = -110  # standard juice assumed for sizing


# ── Data Loading ──

def load_data():
    """Load all features needed for the backtest."""
    conn = psycopg2.connect(DB)

    # Load bridge
    bridge = pd.read_csv(
        "/Users/connorrainey/nhc-capital/nhl-betting/model/player_odds_bridge.csv"
    )
    bridge_map = dict(zip(bridge["bp_player_id"], bridge["player_id"]))

    # Main data: player_stats + pp_stats + games
    query = """
    SELECT
        ps.player_id, ps.game_id, ps.shots, ps.position_code,
        ps.toi_minutes, ps.is_home, ps.team_id,
        pp.pp_toi_seconds / 60.0 AS pp_toi_minutes,
        g.game_date, g.season AS season_id
    FROM player_stats ps
    JOIN player_pp_stats pp ON ps.player_id = pp.player_id AND ps.game_id = pp.game_id
    JOIN games g ON ps.game_id = g.game_id
    WHERE ps.position_code IN ('C','L','R','D')
      AND ps.shots IS NOT NULL
    ORDER BY ps.player_id, g.game_date
    """
    df = pd.read_sql(query, conn)

    # Opponent SOG allowed
    opp_query = """
    SELECT ps.game_id, ps.player_id, gts_opp.shots_on_goal AS opp_sog_allowed
    FROM player_stats ps
    JOIN game_team_stats gts_opp
        ON gts_opp.game_id = ps.game_id AND gts_opp.team_id != ps.team_id
    """
    opp = pd.read_sql(opp_query, conn)
    df = df.merge(opp[["game_id", "player_id", "opp_sog_allowed"]], on=["game_id", "player_id"], how="left")

    # SOG odds (consensus line = avg across books per player per date)
    odds_query = """
    SELECT bp_player_id, event_date, AVG(line) AS consensus_line,
           AVG(over_odds) AS avg_over_odds, AVG(under_odds) AS avg_under_odds
    FROM sog_odds
    WHERE line IS NOT NULL
    GROUP BY bp_player_id, event_date
    """
    odds = pd.read_sql(odds_query, conn)
    odds["player_id"] = odds["bp_player_id"].map(bridge_map)
    odds = odds.dropna(subset=["player_id"])
    odds["player_id"] = odds["player_id"].astype(int)
    odds["event_date"] = pd.to_datetime(odds["event_date"])

    conn.close()

    # Merge odds
    df["game_date"] = pd.to_datetime(df["game_date"])
    df = df.merge(
        odds[["player_id", "event_date", "consensus_line", "avg_over_odds", "avg_under_odds"]],
        left_on=["player_id", "game_date"],
        right_on=["player_id", "event_date"],
        how="inner",
    )

    return df


def build_features(df):
    """Build all rolling features."""
    df = df.sort_values(["player_id", "game_date"]).copy()
    grp = df.groupby("player_id")

    # SOG rolling
    for w in [5, 10, 20]:
        df[f"sog_avg_{w}"] = grp["shots"].transform(
            lambda x: x.shift(1).rolling(w, min_periods=max(1, w // 2)).mean()
        )

    # TOI rolling (only 5-game, dropping 10 per spec)
    df["toi_avg_5"] = grp["toi_minutes"].transform(
        lambda x: x.shift(1).rolling(5, min_periods=2).mean()
    )

    # PP TOI rolling
    for w in [5, 10]:
        df[f"pp_toi_avg_{w}"] = grp["pp_toi_minutes"].transform(
            lambda x: x.shift(1).rolling(w, min_periods=max(1, w // 2)).mean()
        )

    # Opponent SOG allowed rolling
    df["sog_allowed_avg_10"] = grp["opp_sog_allowed"].transform(
        lambda x: x.shift(1).rolling(10, min_periods=3).mean()
    )

    # Team book bias: rolling avg of (actual shots - consensus_line) per team
    df["beat_line"] = df["shots"] - df["consensus_line"]
    team_grp = df.groupby("team_id")
    df["team_book_bias"] = team_grp["beat_line"].transform(
        lambda x: x.shift(1).rolling(50, min_periods=10).mean()
    )

    # Categoricals
    df["is_home_int"] = df["is_home"].astype(int)
    df["is_forward"] = df["position_code"].isin(["C", "L", "R"]).astype(int)

    return df


# ── Model Training & Prediction ──

FEATURES = [
    "sog_avg_20", "sog_avg_10", "sog_avg_5",
    "pp_toi_avg_10", "pp_toi_avg_5",
    "toi_avg_5",
    "sog_allowed_avg_10",
    "is_home_int",
    "team_book_bias",
]

XGB_PARAMS = {
    "n_estimators": 300,
    "max_depth": 4,
    "learning_rate": 0.05,
    "min_child_weight": 50,
    "subsample": 0.7,
    "colsample_bytree": 0.6,
    "reg_alpha": 0.5,
    "reg_lambda": 0.5,
    "random_state": 42,
    "verbosity": 0,
}


def train_and_predict(df):
    """Train separate F/D models, walk-forward on held-out season."""
    # Identify held-out season (latest full season with odds data)
    seasons = sorted(df["season_id"].unique())
    print(f"Seasons available: {seasons}")

    # Use 2023-24 as test (best odds coverage), train on 2022-23
    # (2024-25 has zero odds, 2025-26 has only 3 dates)
    test_season = 20232024
    train_seasons = [s for s in seasons if s < test_season]
    print(f"Train: {train_seasons}, Test: {test_season}")

    train_df = df[df["season_id"].isin(train_seasons)].dropna(subset=FEATURES + ["shots"])
    test_df = df[df["season_id"] == test_season].dropna(subset=FEATURES + ["shots"])

    print(f"Train rows: {len(train_df):,}, Test rows: {len(test_df):,}")
    print(f"Train dates: {train_df['game_date'].min()} to {train_df['game_date'].max()}")
    print(f"Test dates:  {test_df['game_date'].min()} to {test_df['game_date'].max()}")

    # Train separate models
    predictions = []
    for pos_label, pos_mask_val in [("Forward", 1), ("Defense", 0)]:
        tr = train_df[train_df["is_forward"] == pos_mask_val]
        te = test_df[test_df["is_forward"] == pos_mask_val]

        if len(tr) < 100 or len(te) < 50:
            print(f"  {pos_label}: skipped (too few rows)")
            continue

        model = XGBRegressor(**XGB_PARAMS)
        # For D model, don't include is_forward (it's constant)
        feats = [f for f in FEATURES if f != "is_forward"]
        model.fit(tr[feats], tr["shots"])
        te = te.copy()
        te["predicted"] = model.predict(te[feats])
        te["model_type"] = pos_label
        predictions.append(te)

        mae = np.mean(np.abs(te["shots"] - te["predicted"]))
        print(f"  {pos_label}: {len(tr):,} train, {len(te):,} test, MAE={mae:.4f}")

    results = pd.concat(predictions, ignore_index=True)
    return results


# ── Betting Logic ──

def american_to_decimal(odds):
    """Convert American odds to decimal odds."""
    if odds is None or pd.isna(odds):
        return 1.91  # default -110
    if odds > 0:
        return 1 + odds / 100
    return 1 + 100 / abs(odds)


def implied_prob(decimal_odds):
    """Implied probability from decimal odds."""
    return 1 / decimal_odds


def kelly_bet(edge, odds, fraction=KELLY_FRACTION):
    """Quarter-Kelly bet size as fraction of bankroll."""
    dec = american_to_decimal(odds)
    b = dec - 1  # net odds
    p = edge  # estimated true probability of winning
    q = 1 - p
    if b <= 0:
        return 0
    kelly = (b * p - q) / b
    return max(0, kelly * fraction)


def evaluate_bets(results):
    """Flag bets, compute P&L, Kelly sizing."""
    results = results.copy()
    results["edge"] = results["predicted"] - results["consensus_line"]
    results["abs_edge"] = results["edge"].abs()
    results["direction"] = np.where(results["edge"] > 0, "OVER", "UNDER")

    # Only bet when |edge| > threshold
    bets = results[results["abs_edge"] >= EDGE_THRESHOLD].copy()

    # Determine if bet won
    # OVER wins if actual > line, UNDER wins if actual < line, push if equal
    bets["actual_vs_line"] = bets["shots"] - bets["consensus_line"]
    won = np.where(
        bets["direction"] == "OVER",
        bets["shots"] > bets["consensus_line"],
        bets["shots"] < bets["consensus_line"],
    )
    bets["push"] = bets["shots"] == bets["consensus_line"]
    # Use float so NaN works for pushes
    bets["won"] = won.astype(float)
    bets.loc[bets["push"], "won"] = np.nan

    # Odds for the bet
    bets["bet_odds"] = np.where(
        bets["direction"] == "OVER",
        bets["avg_over_odds"],
        bets["avg_under_odds"],
    )
    bets["bet_odds"] = bets["bet_odds"].fillna(VIG_ODDS)
    bets["dec_odds"] = bets["bet_odds"].apply(american_to_decimal)

    # P&L per unit
    bets["pnl_flat"] = np.where(
        bets["push"], 0,
        np.where(bets["won"], bets["dec_odds"] - 1, -1)
    )

    # Kelly sizing
    # Estimate win probability from model edge (simple logistic approximation)
    # For over: P(shots > line) ≈ based on model prediction
    # Rough: use historical calibration — if model says predicted=X, line=L
    # P(over) ≈ 0.5 + 0.15 * (X - L) capped [0.3, 0.8]
    bets["est_win_prob"] = (0.5 + 0.15 * bets["edge"]).clip(0.3, 0.85)
    bets["kelly_frac"] = bets.apply(
        lambda r: kelly_bet(r["est_win_prob"], r["bet_odds"]), axis=1
    )
    bets["kelly_units"] = bets["kelly_frac"] * UNIT_SIZE
    bets["pnl_kelly"] = np.where(
        bets["push"], 0,
        np.where(bets["won"], bets["kelly_units"] * (bets["dec_odds"] - 1), -bets["kelly_units"])
    )

    # Line bucket
    bets["line_bucket"] = pd.cut(
        bets["consensus_line"],
        bins=[0, 2, 3, 4, 10],
        labels=["0-2", "2-3", "3-4", "4+"],
    )

    # Edge bucket
    bets["edge_bucket"] = pd.cut(
        bets["abs_edge"],
        bins=[0.75, 1.0, 1.5, 10],
        labels=["0.75-1.0", "1.0-1.5", "1.5+"],
    )

    # Team name lookup
    conn = psycopg2.connect(DB)
    teams = pd.read_sql("SELECT team_id, team_name AS name FROM teams", conn)
    conn.close()
    bets = bets.merge(teams, on="team_id", how="left")

    return bets


# ── Reporting ──

def print_breakdown(bets, group_col, label):
    """Print win rate and ROI breakdown by a column."""
    print(f"\n--- {label} ---")
    print(f"{'Group':<20} {'Bets':>6} {'Wins':>6} {'Win%':>7} {'ROI%':>8} {'P&L':>10}")
    print("-" * 60)
    non_push = bets[~bets["push"]].copy()
    for grp, sub in non_push.groupby(group_col, observed=True):
        n = len(sub)
        wins = sub["won"].sum()
        wr = wins / n * 100 if n > 0 else 0
        roi = sub["pnl_flat"].sum() / n * 100 if n > 0 else 0
        pnl = sub["pnl_flat"].sum()
        print(f"{str(grp):<20} {n:>6} {int(wins):>6} {wr:>6.1f}% {roi:>+7.1f}% {pnl:>+10.2f}u")


def generate_summary(bets, results):
    """Generate full summary."""
    non_push = bets[~bets["push"]].copy()
    total_bets = len(non_push)
    wins = non_push["won"].sum()
    win_rate = wins / total_bets * 100 if total_bets > 0 else 0
    roi = non_push["pnl_flat"].sum() / total_bets * 100 if total_bets > 0 else 0
    total_pnl = non_push["pnl_flat"].sum()
    pushes = bets["push"].sum()

    # Book MAE vs model MAE
    test_with_line = results.dropna(subset=["consensus_line", "shots"])
    book_mae = np.mean(np.abs(test_with_line["shots"] - test_with_line["consensus_line"]))
    model_mae = np.mean(np.abs(test_with_line["shots"] - test_with_line["predicted"]))

    print("\n" + "=" * 60)
    print("SOG MODEL BACKTEST RESULTS")
    print("=" * 60)

    print("\nOverall MAE:")
    print(f"  Book (consensus line): {book_mae:.4f}")
    print(f"  Model prediction:      {model_mae:.4f}")
    print(f"  Improvement:           {book_mae - model_mae:+.4f} ({(book_mae - model_mae)/book_mae*100:+.1f}%)")

    print(f"\nBetting Summary (edge threshold: {EDGE_THRESHOLD}):")
    print(f"  Total bets:  {total_bets} (+ {int(pushes)} pushes)")
    print(f"  Wins:        {int(wins)}")
    print(f"  Win rate:    {win_rate:.1f}%")
    print(f"  ROI:         {roi:+.1f}%")
    print(f"  Total P&L:   {total_pnl:+.2f} units")

    # Kelly stats
    kelly_pnl = non_push["pnl_kelly"].sum()
    cum_kelly = non_push["pnl_kelly"].cumsum()
    max_dd_kelly = (cum_kelly.cummax() - cum_kelly).max()
    kelly_returns = non_push["pnl_kelly"] / UNIT_SIZE
    sharpe = kelly_returns.mean() / kelly_returns.std() * np.sqrt(252) if kelly_returns.std() > 0 else 0

    print("\nKelly Sizing ($100 unit, quarter-Kelly):")
    print(f"  Total P&L:     ${kelly_pnl:+,.2f}")
    print(f"  Max drawdown:  ${max_dd_kelly:,.2f}")
    print(f"  Sharpe ratio:  {sharpe:.2f}")
    print(f"  Avg bet size:  ${non_push['kelly_units'].mean():.2f}")

    # Breakdowns
    print_breakdown(bets, "line_bucket", "By Line Bucket")
    print_breakdown(bets, "model_type", "By Position (F vs D)")
    print_breakdown(bets, "direction", "By Direction (Over vs Under)")
    print_breakdown(bets, "edge_bucket", "By Edge Size")

    # Top 10 teams by P&L
    print("\n--- Top 10 Teams by P&L ---")
    team_pnl = non_push.groupby("name").agg(
        bets=("won", "count"),
        wins=("won", "sum"),
        pnl=("pnl_flat", "sum"),
    )
    team_pnl["wr"] = team_pnl["wins"] / team_pnl["bets"] * 100
    team_pnl["roi"] = team_pnl["pnl"] / team_pnl["bets"] * 100
    team_pnl = team_pnl.sort_values("pnl", ascending=False)
    print(f"{'Team':<25} {'Bets':>6} {'Win%':>7} {'ROI%':>8} {'P&L':>10}")
    print("-" * 60)
    for name, row in team_pnl.head(10).iterrows():
        print(f"{name:<25} {int(row['bets']):>6} {row['wr']:>6.1f}% {row['roi']:>+7.1f}% {row['pnl']:>+10.2f}u")

    return {
        "book_mae": book_mae, "model_mae": model_mae,
        "total_bets": total_bets, "wins": int(wins), "win_rate": win_rate,
        "roi": roi, "total_pnl": total_pnl,
        "kelly_pnl": kelly_pnl, "max_dd": max_dd_kelly, "sharpe": sharpe,
    }


def save_to_db(bets):
    """Save full backtest results to database."""
    conn = psycopg2.connect(DB)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS sog_backtest_results")
    cur.execute("""
        CREATE TABLE sog_backtest_results (
            player_id INTEGER,
            game_id INTEGER,
            game_date DATE,
            player_name TEXT,
            team_name TEXT,
            position TEXT,
            model_type TEXT,
            predicted REAL,
            consensus_line REAL,
            actual_shots INTEGER,
            edge REAL,
            direction TEXT,
            bet_odds REAL,
            won BOOLEAN,
            push BOOLEAN,
            pnl_flat REAL,
            kelly_units REAL,
            pnl_kelly REAL,
            line_bucket TEXT,
            edge_bucket TEXT,
            PRIMARY KEY (player_id, game_id)
        )
    """)
    conn.commit()

    # Get player names
    names = pd.read_sql(
        "SELECT DISTINCT player_id, player_name FROM player_pp_stats",
        conn,
    )
    bets = bets.merge(names, on="player_id", how="left")

    insert = """
    INSERT INTO sog_backtest_results (
        player_id, game_id, game_date, player_name, team_name, position,
        model_type, predicted, consensus_line, actual_shots, edge, direction,
        bet_odds, won, push, pnl_flat, kelly_units, pnl_kelly, line_bucket, edge_bucket
    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (player_id, game_id) DO NOTHING
    """
    rows = []
    for _, r in bets.iterrows():
        rows.append((
            int(r["player_id"]), int(r["game_id"]),
            r["game_date"].date() if hasattr(r["game_date"], "date") else r["game_date"],
            r.get("player_name"), r.get("name"),
            r["position_code"], r["model_type"],
            float(r["predicted"]), float(r["consensus_line"]),
            int(r["shots"]), float(r["edge"]), r["direction"],
            float(r["bet_odds"]),
            None if pd.isna(r["won"]) else bool(r["won"]),
            bool(r["push"]),
            float(r["pnl_flat"]), float(r["kelly_units"]), float(r["pnl_kelly"]),
            str(r["line_bucket"]) if pd.notna(r["line_bucket"]) else None,
            str(r["edge_bucket"]) if pd.notna(r["edge_bucket"]) else None,
        ))

    batch = 500
    for i in range(0, len(rows), batch):
        cur.executemany(insert, rows[i:i + batch])
        conn.commit()

    cur.close()
    conn.close()
    print(f"\nSaved {len(rows)} bet rows to sog_backtest_results table")


def plot_pnl(bets, out_path):
    """Plot cumulative P&L curves."""
    non_push = bets[~bets["push"]].sort_values("game_date").copy()

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), facecolor="#0f1117")
    for ax in [ax1, ax2]:
        ax.set_facecolor("#181a20")
        ax.tick_params(colors="#8b8f9a")
        ax.spines["bottom"].set_color("#2a2d37")
        ax.spines["left"].set_color("#2a2d37")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

    # Flat unit P&L
    cum_flat = non_push["pnl_flat"].cumsum()
    ax1.plot(range(len(cum_flat)), cum_flat.values, color="#4f8cff", linewidth=1.5, label="Flat (1u)")
    ax1.axhline(0, color="#5f6370", linewidth=0.5, linestyle="--")
    ax1.set_title("Cumulative P&L — Flat Units", color="#e4e5e9", fontsize=14)
    ax1.set_ylabel("Units", color="#8b8f9a")
    ax1.legend(facecolor="#181a20", edgecolor="#2a2d37", labelcolor="#e4e5e9")

    # Add over/under split
    over = non_push[non_push["direction"] == "OVER"]
    under = non_push[non_push["direction"] == "UNDER"]
    cum_over = over["pnl_flat"].cumsum()
    cum_under = under["pnl_flat"].cumsum()
    ax1.plot(range(len(cum_over)), cum_over.values, color="#22c55e", linewidth=1, alpha=0.7, label="Over bets")
    ax1.plot(range(len(cum_under)), cum_under.values, color="#ef4444", linewidth=1, alpha=0.7, label="Under bets")
    ax1.legend(facecolor="#181a20", edgecolor="#2a2d37", labelcolor="#e4e5e9")

    # Kelly P&L
    cum_kelly = non_push["pnl_kelly"].cumsum()
    ax2.plot(range(len(cum_kelly)), cum_kelly.values, color="#a855f7", linewidth=1.5, label=f"Quarter-Kelly (${UNIT_SIZE} base)")
    ax2.axhline(0, color="#5f6370", linewidth=0.5, linestyle="--")
    ax2.set_title("Cumulative P&L — Quarter-Kelly", color="#e4e5e9", fontsize=14)
    ax2.set_xlabel("Bet #", color="#8b8f9a")
    ax2.set_ylabel("Dollars ($)", color="#8b8f9a")

    # Max drawdown annotation
    dd = (cum_kelly.cummax() - cum_kelly)
    dd_idx = dd.idxmax() if len(dd) > 0 else None
    if dd_idx is not None and dd.max() > 0:
        dd_bet_num = non_push.index.get_loc(dd_idx) if dd_idx in non_push.index else 0
        ax2.annotate(
            f"Max DD: ${dd.max():,.0f}",
            xy=(dd_bet_num, cum_kelly.iloc[dd_bet_num] if dd_bet_num < len(cum_kelly) else 0),
            color="#ef4444", fontsize=10,
        )

    ax2.legend(facecolor="#181a20", edgecolor="#2a2d37", labelcolor="#e4e5e9")

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, facecolor="#0f1117")
    plt.close()
    print(f"P&L chart saved: {out_path}")


def save_summary_md(metrics, bets, out_path):
    """Save clean markdown summary."""
    non_push = bets[~bets["push"]]

    # Direction breakdown
    over = non_push[non_push["direction"] == "OVER"]
    under = non_push[non_push["direction"] == "UNDER"]
    over_wr = over["won"].mean() * 100 if len(over) > 0 else 0
    under_wr = under["won"].mean() * 100 if len(under) > 0 else 0
    over_roi = over["pnl_flat"].sum() / len(over) * 100 if len(over) > 0 else 0
    under_roi = under["pnl_flat"].sum() / len(under) * 100 if len(under) > 0 else 0

    md = f"""# SOG Model Backtest Summary

## Model Performance
| Metric | Book Line | Model |
|---|---|---|
| MAE | {metrics['book_mae']:.4f} | {metrics['model_mae']:.4f} |

Model improvement: **{metrics['book_mae'] - metrics['model_mae']:+.4f}** ({(metrics['book_mae'] - metrics['model_mae'])/metrics['book_mae']*100:+.1f}%)

## Betting Results (edge > {EDGE_THRESHOLD})
- **Total bets:** {metrics['total_bets']}
- **Win rate:** {metrics['win_rate']:.1f}%
- **ROI:** {metrics['roi']:+.1f}%
- **Total P&L:** {metrics['total_pnl']:+.2f} units

## Kelly Sizing ($100 unit, quarter-Kelly)
- **Total P&L:** ${metrics['kelly_pnl']:+,.2f}
- **Max drawdown:** ${metrics['max_dd']:,.2f}
- **Sharpe ratio:** {metrics['sharpe']:.2f}

## Direction Breakdown
| Direction | Bets | Win% | ROI% |
|---|---|---|---|
| OVER | {len(over)} | {over_wr:.1f}% | {over_roi:+.1f}% |
| UNDER | {len(under)} | {under_wr:.1f}% | {under_roi:+.1f}% |

## Features Used
sog_avg_20, sog_avg_10, sog_avg_5, pp_toi_avg_10, pp_toi_avg_5, toi_avg_5,
sog_allowed_avg_10, is_home, team_book_bias

Separate models for Forwards and Defensemen. XGBoost (300 trees, depth 4, lr 0.05).
Walk-forward validation: train on prior seasons, test on held-out season.
"""
    with open(out_path, "w") as f:
        f.write(md)
    print(f"Summary saved: {out_path}")


# ── Main ──

def main():
    print("Loading data...")
    df = load_data()
    print(f"Rows with odds: {len(df):,}")

    print("\nBuilding features...")
    df = build_features(df)

    print("\nTraining models & predicting...")
    results = train_and_predict(df)

    print("\nEvaluating bets...")
    bets = evaluate_bets(results)

    metrics = generate_summary(bets, results)

    print("\nSaving to database...")
    save_to_db(bets)

    print("\nGenerating P&L chart...")
    plot_pnl(bets, "/Users/connorrainey/nhc-capital/nhl-betting/model/pnl_curve.png")

    print("\nSaving summary markdown...")
    save_summary_md(
        metrics, bets,
        "/Users/connorrainey/nhc-capital/nhl-betting/docs/backtest_summary.md",
    )

    print("\n✅ Full backtest complete!")


if __name__ == "__main__":
    main()
