"""Shared goalie saves strategy training and live inference helpers."""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import psycopg2
from model.bankroll import kelly_size

try:
    from .db_config import get_dsn
except ImportError:
    from db_config import get_dsn

MODEL_DIR = Path(__file__).resolve().parent
FEATURE_MATRIX_PATH = MODEL_DIR / "feature_matrix.pkl"

GOALIE_STRATEGY_FEATURES = [
    "sa_avg_10",
    "sa_avg_20",
    "svpct_avg_10",
    "svpct_avg_20",
    "is_home",
    "opp_team_sog_avg_10",
    "days_rest",
    "own_def_missing_toi",
    "opp_corsi_pct_avg_10",
    "opp_corsi_diff_avg_10",
    "own_corsi_pct_avg_10",
    "pull_rate_10",
    "starts_last_7d",
    "opp_team_pp_opps_avg_10",
]

STRATEGY_MODEL_PARAMS = {
    "objective": "regression",
    "num_leaves": 10,
    "max_depth": 4,
    "min_child_samples": 50,
    "learning_rate": 0.05,
    "n_estimators": 300,
    "reg_alpha": 0.5,
    "reg_lambda": 0.5,
    "feature_fraction": 0.6,
    "bagging_fraction": 0.7,
    "bagging_freq": 5,
    "verbose": -1,
}

def load_feature_matrix() -> pd.DataFrame:
    """Load the historical feature matrix used by the research stack."""
    matrix = pd.read_pickle(FEATURE_MATRIX_PATH)
    matrix["event_date"] = pd.to_datetime(matrix["event_date"])
    return matrix


def get_strategy_feature_columns(frame: pd.DataFrame) -> list[str]:
    """Return the direct-saves strategy feature set available in a frame."""
    return [feature for feature in GOALIE_STRATEGY_FEATURES if feature in frame.columns]


def compute_strategy_thresholds(frame: pd.DataFrame) -> dict[str, float]:
    """Compute strategy thresholds from training data only."""
    thresholds: dict[str, float] = {}

    def _quantile(column: str, q: float) -> float | None:
        if column not in frame.columns:
            return None
        series = frame[column].dropna()
        if series.empty:
            return None
        return float(series.quantile(q))

    thresholds["opp_corsi_q25"] = _quantile("opp_corsi_pct_avg_10", 0.25)
    thresholds["opp_corsi_q75"] = _quantile("opp_corsi_pct_avg_10", 0.75)
    thresholds["opp_corsi_diff_q25"] = _quantile("opp_corsi_diff_avg_10", 0.25)
    thresholds["opp_corsi_diff_q75"] = _quantile("opp_corsi_diff_avg_10", 0.75)
    thresholds["opp_puck_q75"] = _quantile("opp_puck_control_avg_10", 0.75)
    return thresholds


def train_strategy_model(train_frame: pd.DataFrame) -> tuple[lgb.LGBMRegressor, list[str]]:
    """Train the direct-saves strategy model on the research matrix."""
    feature_cols = get_strategy_feature_columns(train_frame)
    train_df = train_frame.dropna(subset=["saves"])
    valid_mask = train_df[feature_cols].notna().any(axis=1)
    train_df = train_df[valid_mask]

    if len(train_df) < 100:
        raise ValueError(f"Not enough goalie strategy training rows: {len(train_df)}")

    model = lgb.LGBMRegressor(**STRATEGY_MODEL_PARAMS)
    model.fit(train_df[feature_cols].fillna(-999), train_df["saves"])
    return model, feature_cols


def _get_conn():
    return psycopg2.connect(get_dsn())


def _to_date(value) -> date_type:
    if isinstance(value, str):
        return date_type.fromisoformat(value)
    return value


def _odds_to_implied(odds: int | float) -> float:
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    return 100 / (odds + 100)


def _fetch_team_context(cur, team_id: int, game_date) -> dict[str, float] | None:
    cur.execute(
        """
        SELECT gts.game_id, gts.shots_attempted, gts.shots_on_goal,
               gts.takeaways, gts.giveaways, gts.power_play_opportunities,
               g.game_date
        FROM game_team_stats gts
        JOIN games g ON gts.game_id = g.game_id
        WHERE gts.team_id = %s AND g.game_date < %s
        ORDER BY g.game_date DESC
        LIMIT 10
        """,
        (team_id, game_date),
    )
    history = cur.fetchall()
    if len(history) < 3:
        return None

    sog_avg = float(np.mean([row[2] or 0 for row in history]))
    pp_avg = float(np.mean([row[5] or 0 for row in history]))
    puck_avg = float(np.mean([(row[3] or 0) - (row[4] or 0) for row in history]))

    corsi_pcts = []
    corsi_diffs = []
    for row in history:
        hist_game_id, shots_attempted = row[0], row[1] or 0
        cur.execute(
            """
            SELECT shots_attempted
            FROM game_team_stats
            WHERE game_id = %s AND team_id != %s
            LIMIT 1
            """,
            (hist_game_id, team_id),
        )
        opponent = cur.fetchone()
        if not opponent or opponent[0] is None:
            continue
        total = shots_attempted + opponent[0]
        if total <= 0:
            continue
        corsi_pcts.append(shots_attempted / total)
        corsi_diffs.append(shots_attempted - opponent[0])

    if not corsi_pcts:
        return None

    return {
        "opp_team_sog_avg_10": sog_avg,
        "opp_team_pp_opps_avg_10": pp_avg,
        "opp_puck_control_avg_10": puck_avg,
        "opp_corsi_pct_avg_10": float(np.mean(corsi_pcts)),
        "opp_corsi_diff_avg_10": float(np.mean(corsi_diffs)),
    }


def _build_live_goalie_features(events: list[dict], target_date: str) -> list[dict]:
    """Build live goalie features for tonight using DB history."""
    target_dt = pd.to_datetime(target_date).date()
    # game_date column is text in DB — use string for SQL comparisons
    target_dt_str = str(target_dt)
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute("SELECT team_id, team_name, tri_code FROM teams WHERE active = 1")
    teams = cur.fetchall()
    team_lookup = {team_name.lower(): (team_id, tri_code) for team_id, team_name, tri_code in teams}

    def _resolve_team(team_name: str):
        parts = team_name.lower().split()
        for idx in range(len(parts)):
            candidate = " ".join(parts[idx:])
            if candidate in team_lookup:
                return team_lookup[candidate]
        return None, None

    event_lookup = {event["id"]: event for event in events}
    rows: list[dict] = []

    from pipeline.odds_pull import get_best_odds, pull_player_props

    saves_props = pull_player_props(events, markets=["player_total_saves"])
    if not saves_props:
        conn.close()
        return []

    best = get_best_odds(saves_props)
    grouped_props: dict[tuple[str, str], dict] = defaultdict(dict)
    for (player_name, market, side, line), offer in best.items():
        if market != "player_total_saves":
            continue
        grouped_props[(player_name, str(offer["event_id"]))][side] = {
            "line": line,
            "offer": offer,
        }

    for (player_name, event_id), markets in grouped_props.items():
        event = event_lookup.get(event_id)
        if not event:
            continue

        cur.execute(
            """
            SELECT p.player_id,
                   p.first_name || ' ' || p.last_name AS goalie_name,
                   gs.team_id
            FROM players p
            JOIN goalie_stats gs ON gs.player_id = p.player_id
            JOIN games g ON g.game_id = gs.game_id
            WHERE LOWER(p.first_name || ' ' || p.last_name) = LOWER(%s)
              AND gs.started = 1
              AND g.game_date < %s
            ORDER BY g.game_date DESC
            LIMIT 1
            """,
            (player_name, target_dt_str),
        )
        goalie = cur.fetchone()

        if not goalie:
            last_name = player_name.split()[-1]
            cur.execute(
                """
                SELECT p.player_id,
                       p.first_name || ' ' || p.last_name AS goalie_name,
                       gs.team_id
                FROM players p
                JOIN goalie_stats gs ON gs.player_id = p.player_id
                JOIN games g ON g.game_id = gs.game_id
                WHERE LOWER(p.last_name) = LOWER(%s)
                  AND gs.started = 1
                  AND g.game_date < %s
                ORDER BY g.game_date DESC
                LIMIT 1
                """,
                (last_name, target_dt_str),
            )
            goalie = cur.fetchone()

        if not goalie:
            continue

        player_id, resolved_name, team_id = goalie
        home_id, home_tri = _resolve_team(event["home_team"])
        away_id, away_tri = _resolve_team(event["away_team"])
        is_home = int(team_id == home_id)
        opp_team_id = away_id if is_home else home_id
        tri_code = home_tri if is_home else away_tri

        if opp_team_id is None:
            continue

        cur.execute(
            """
            SELECT gs.saves,
                   gs.shots_against,
                   gs.save_pct,
                   g.game_date,
                   COALESCE(ga.incomplete_games, 0) AS incomplete_games
            FROM goalie_stats gs
            JOIN games g ON g.game_id = gs.game_id
            LEFT JOIN goalie_advanced ga
              ON ga.game_id = gs.game_id AND ga.player_id = gs.player_id
            WHERE gs.player_id = %s
              AND gs.started = 1
              AND gs.shots_against > 0
              AND g.game_date < %s
            ORDER BY g.game_date DESC
            LIMIT 20
            """,
            (player_id, target_dt_str),
        )
        history = list(reversed(cur.fetchall()))
        if len(history) < 5:
            continue

        last10 = history[-10:]
        last20 = history[-20:]
        last_game_date = _to_date(history[-1][3])

        cur.execute(
            """
            SELECT gts.game_id,
                   gts.shots_attempted,
                   gts.shots_on_goal,
                   gts.takeaways,
                   gts.giveaways,
                   gts.power_play_opportunities
            FROM game_team_stats gts
            JOIN games g ON g.game_id = gts.game_id
            WHERE gts.team_id = %s
              AND g.game_date < %s
            ORDER BY g.game_date DESC
            LIMIT 10
            """,
            (team_id, target_dt_str),
        )
        own_history = cur.fetchall()
        own_corsi = []
        for hist_game_id, shots_attempted, *_ in own_history:
            cur.execute(
                """
                SELECT shots_attempted
                FROM game_team_stats
                WHERE game_id = %s AND team_id != %s
                LIMIT 1
                """,
                (hist_game_id, team_id),
            )
            opponent = cur.fetchone()
            if not opponent or opponent[0] is None:
                continue
            total = (shots_attempted or 0) + opponent[0]
            if total > 0:
                own_corsi.append((shots_attempted or 0) / total)

        opp_context = _fetch_team_context(cur, opp_team_id, target_dt_str)
        if not opp_context or not own_corsi:
            continue

        days_rest = max((target_dt - last_game_date).days, 0)
        starts_last_7d = sum(
            1 for _, _, _, game_date, _ in history
            if (target_dt - _to_date(game_date)).days <= 7
        )
        pull_rate_10 = float(np.mean([row[4] == 1 for row in last10]))

        feature_row = {
            "player": resolved_name,
            "player_team": tri_code or "",
            "game": f"{event['away_team']} @ {event['home_team']}",
            "event_id": event["id"],
            "line": float(next(iter(markets.values()))["line"]),
            "sa_avg_10": float(np.mean([row[1] or 0 for row in last10])),
            "sa_avg_20": float(np.mean([row[1] or 0 for row in last20])),
            "svpct_avg_10": float(np.mean([row[2] for row in last10 if row[2] is not None])),
            "svpct_avg_20": float(np.mean([row[2] for row in last20 if row[2] is not None])),
            "is_home": is_home,
            "days_rest": days_rest,
            "own_def_missing_toi": 0.0,
            "own_corsi_pct_avg_10": float(np.mean(own_corsi)),
            "pull_rate_10": pull_rate_10,
            "starts_last_7d": starts_last_7d,
            **opp_context,
            "over_offer": markets.get("Over", {}).get("offer"),
            "under_offer": markets.get("Under", {}).get("offer"),
        }
        rows.append(feature_row)

    conn.close()
    return rows


def run_live_goalie_saves(
    events: list[dict],
    target_date: str | None = None,
    bankroll=None,
) -> list[dict]:
    """Run the live goalie saves strategy using the shared model stack."""
    if not events:
        return []

    if target_date is None:
        commence = events[0].get("commence_time")
        target_date = commence[:10] if commence else pd.Timestamp.today().strftime("%Y-%m-%d")

    matrix = load_feature_matrix()
    train_df = matrix[matrix["event_date"] < pd.to_datetime(target_date)].copy()
    model, feature_cols = train_strategy_model(train_df)
    thresholds = compute_strategy_thresholds(train_df)
    live_rows = _build_live_goalie_features(events, target_date)

    picks = []
    for row in live_rows:
        pred = float(
            model.predict(pd.DataFrame([{feature: row.get(feature, -999) for feature in feature_cols}]).fillna(-999))[0]
        )
        line = row["line"]
        gap = abs(pred - line)
        side = "under" if pred < line else "over"

        if (
            side == "under"
            and thresholds.get("opp_corsi_q25") is not None
            and row["opp_corsi_pct_avg_10"] < thresholds["opp_corsi_q25"]
            and row["under_offer"]
        ):
            under_offer = row["under_offer"]
            if 1.0 <= gap < 1.5:
                win_prob = 0.723
                implied = _odds_to_implied(under_offer["odds"])
                edge = win_prob - implied
                units, dollars = kelly_size(
                    win_prob=win_prob,
                    odds=under_offer["odds"],
                    bankroll=bankroll,
                )
                if edge > 0.02 and units > 0:
                    picks.append(
                        {
                            "player": row["player"],
                            "player_team": row["player_team"],
                            "game": row["game"],
                            "event_id": row["event_id"],
                            "strategy": "A: MF3a UNDER",
                            "bet": f"UNDER {line} saves",
                            "odds": under_offer["odds"],
                            "book": under_offer["book"],
                            "book_title": under_offer["book_title"],
                            "edge": edge,
                            "confidence": "HIGH" if edge >= 0.08 else "MEDIUM",
                            "units": units,
                            "dollars": dollars,
                            "pred": round(pred, 1),
                            "line": line,
                            "gap": round(gap, 1),
                            "sub_strategy": "MF3a",
                        }
                    )
            if gap >= 2.5 and not any(p["player"] == row["player"] and p["sub_strategy"] == "MF3a" for p in picks):
                win_prob = 0.652
                implied = _odds_to_implied(under_offer["odds"])
                edge = win_prob - implied
                units, dollars = kelly_size(
                    win_prob=win_prob,
                    odds=under_offer["odds"],
                    bankroll=bankroll,
                )
                if edge > 0.02 and units > 0:
                    picks.append(
                        {
                            "player": row["player"],
                            "player_team": row["player_team"],
                            "game": row["game"],
                            "event_id": row["event_id"],
                            "strategy": "A: MF3b UNDER",
                            "bet": f"UNDER {line} saves",
                            "odds": under_offer["odds"],
                            "book": under_offer["book"],
                            "book_title": under_offer["book_title"],
                            "edge": edge,
                            "confidence": "HIGH" if gap >= 3.0 else "MEDIUM",
                            "units": units,
                            "dollars": dollars,
                            "pred": round(pred, 1),
                            "line": line,
                            "gap": round(gap, 1),
                            "sub_strategy": "MF3b",
                        }
                    )

        if side == "under" and gap >= 2.0 and row["days_rest"] <= 1 and row["under_offer"]:
            under_offer = row["under_offer"]
            win_prob = 0.64
            implied = _odds_to_implied(under_offer["odds"])
            edge = win_prob - implied
            units, dollars = kelly_size(
                win_prob=win_prob,
                odds=under_offer["odds"],
                bankroll=bankroll,
            )
            if edge > 0.02 and units > 0 and not any(
                p["player"] == row["player"] and p["sub_strategy"] == "MF2" for p in picks
            ):
                picks.append(
                    {
                        "player": row["player"],
                        "player_team": row["player_team"],
                        "game": row["game"],
                        "event_id": row["event_id"],
                        "strategy": "A: MF2 UNDER (B2B)",
                        "bet": f"UNDER {line} saves",
                        "odds": under_offer["odds"],
                        "book": under_offer["book"],
                        "book_title": under_offer["book_title"],
                        "edge": edge,
                        "confidence": "HIGH" if gap >= 2.5 else "MEDIUM",
                        "units": units,
                        "dollars": dollars,
                        "pred": round(pred, 1),
                        "line": line,
                        "gap": round(gap, 1),
                        "sub_strategy": "MF2",
                    }
                )

        if (
            side == "over"
            and row["over_offer"]
            and thresholds.get("opp_corsi_q75") is not None
            and thresholds.get("opp_corsi_diff_q75") is not None
            and thresholds.get("opp_puck_q75") is not None
            and row["opp_corsi_pct_avg_10"] > thresholds["opp_corsi_q75"]
            and row["opp_corsi_diff_avg_10"] > thresholds["opp_corsi_diff_q75"]
            and row["opp_puck_control_avg_10"] > thresholds["opp_puck_q75"]
        ):
            over_offer = row["over_offer"]
            win_prob = 0.592
            implied = _odds_to_implied(over_offer["odds"])
            edge = win_prob - implied
            units, dollars = kelly_size(
                win_prob=win_prob,
                odds=over_offer["odds"],
                bankroll=bankroll,
            )
            if edge > 0.02 and units > 0:
                picks.append(
                    {
                        "player": row["player"],
                        "player_team": row["player_team"],
                        "game": row["game"],
                        "event_id": row["event_id"],
                        "strategy": "A: PF1 OVER",
                        "bet": f"OVER {line} saves",
                        "odds": over_offer["odds"],
                        "book": over_offer["book"],
                        "book_title": over_offer["book_title"],
                        "edge": edge,
                        "confidence": "HIGH" if edge >= 0.08 else "MEDIUM",
                        "units": units,
                        "dollars": dollars,
                        "pred": round(pred, 1),
                        "line": line,
                        "gap": round(gap, 1),
                        "sub_strategy": "PF1",
                    }
                )

    return picks


__all__ = [
    "GOALIE_STRATEGY_FEATURES",
    "STRATEGY_MODEL_PARAMS",
    "compute_strategy_thresholds",

    "get_strategy_feature_columns",
    "load_feature_matrix",
    "run_live_goalie_saves",
    "train_strategy_model",
]
