"""
Goalie Saves Model — Strategies MF3, MF2, PF1.

Implements the proven strategies from docs/PROVENSTRATEGIES.md:
- MF3: LightGBM UNDER + low opponent Corsi (bottom 25%)
  - MF3a: gap [1.0-1.5) — sharpest signal (72.3% win, +34.3% ROI)
  - Skip dead zone [1.5-2.5)
  - MF3b: gap ≥2.5 — high conviction (65.2% win, +20.6% ROI)
- MF2: LightGBM UNDER + B2B goalie (gap ≥2.0, days_rest ≤1)
- PF1: OVER + triple Corsi filter (top 25% Corsi%, Corsi diff, puck control)

Rolling features built from goalie_stats + game_team_stats tables.
LightGBM regressor trained on all available data (walk-forward in backtest,
full history for live deployment).
"""
import psycopg2
import numpy as np
from collections import defaultdict

try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

DB_CONN = "host=/tmp dbname=nhl_betting user=connorrainey"

# LightGBM params from PROVENSTRATEGIES.md
LGB_PARAMS = {
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

# Quarter Kelly
BANKROLL = 2500
UNIT = 25


def _get_conn():
    return psycopg2.connect(DB_CONN)


def _build_rolling_features():
    """Build rolling goalie + team features from DB.

    Returns dict keyed by (player_id, game_id) with feature vectors,
    plus a list of all rows for quantile computation.
    """
    from datetime import date as date_type

    conn = _get_conn()
    cur = conn.cursor()

    # Get all goalie games with team info
    cur.execute("""
        SELECT gs.player_id, gs.game_id, gs.team_id, gs.is_home,
               gs.saves, gs.shots_against, gs.goals_against,
               gs.save_pct, gs.started,
               g.game_date
        FROM goalie_stats gs
        JOIN games g ON gs.game_id = g.game_id
        WHERE gs.started = 1 AND gs.shots_against > 0
        ORDER BY gs.player_id, g.game_date
    """)
    goalie_rows = cur.fetchall()

    # Get team stats for Corsi etc
    cur.execute("""
        SELECT gts.game_id, gts.team_id, gts.is_home,
               gts.shots_on_goal, gts.shots_attempted,
               gts.takeaways, gts.giveaways,
               gts.power_play_opportunities,
               gts.faceoff_win_pct,
               g.game_date
        FROM game_team_stats gts
        JOIN games g ON gts.game_id = g.game_id
        ORDER BY gts.team_id, g.game_date
    """)
    team_rows = cur.fetchall()
    conn.close()

    # Build team stats history keyed by team_id → list of game dicts
    team_history = defaultdict(list)
    for row in team_rows:
        game_id, team_id, is_home, sog, sa, ta, ga, pp_opp, fo_pct, gdate = row
        team_history[team_id].append({
            "game_id": game_id,
            "game_date": gdate,
            "sog": sog or 0,
            "shots_attempted": sa or 0,
            "takeaways": ta or 0,
            "giveaways": ga or 0,
            "pp_opportunities": pp_opp or 0,
            "faceoff_win_pct": fo_pct or 50.0,
        })

    # Build opponent lookup: for a given game + team → opponent team_id
    game_teams = defaultdict(list)
    for row in team_rows:
        game_id, team_id = row[0], row[1]
        game_teams[game_id].append(team_id)

    def get_opponent(game_id, team_id):
        teams = game_teams.get(game_id, [])
        for t in teams:
            if t != team_id:
                return t
        return None

    # Compute rolling team Corsi features
    def rolling_team_stats(team_id, game_date, window=10):
        """Get rolling Corsi, SOG, puck control for a team BEFORE game_date."""
        history = [g for g in team_history[team_id] if g["game_date"] < game_date]
        history = history[-window:]
        if len(history) < 3:
            return None

        sa_vals = [g["shots_attempted"] for g in history]
        sog_vals = [g["sog"] for g in history]
        ta_vals = [g["takeaways"] for g in history]
        ga_vals = [g["giveaways"] for g in history]
        pp_vals = [g["pp_opportunities"] for g in history]

        # Need opponent SA for each game to compute Corsi%
        corsi_pcts = []
        corsi_diffs = []
        for g in history:
            opp_tid = get_opponent(g["game_id"], team_id)
            if opp_tid:
                opp_games = [og for og in team_history[opp_tid]
                             if og["game_id"] == g["game_id"]]
                if opp_games:
                    opp_sa = opp_games[0]["shots_attempted"]
                    total = g["shots_attempted"] + opp_sa
                    if total > 0:
                        corsi_pcts.append(g["shots_attempted"] / total)
                        corsi_diffs.append(g["shots_attempted"] - opp_sa)

        if not corsi_pcts:
            return None

        return {
            "corsi_pct_avg": np.mean(corsi_pcts),
            "corsi_diff_avg": np.mean(corsi_diffs),
            "sog_avg": np.mean(sog_vals),
            "puck_control_avg": np.mean([t - g for t, g in zip(ta_vals, ga_vals)]),
            "pp_opps_avg": np.mean(pp_vals),
        }

    # Build goalie history and feature rows
    goalie_history = defaultdict(list)
    for row in goalie_rows:
        pid, gid, tid, is_home, saves, sa, ga, svpct, started, gdate = row
        goalie_history[pid].append({
            "game_id": gid,
            "team_id": tid,
            "is_home": is_home,
            "saves": saves or 0,
            "shots_against": sa or 0,
            "goals_against": ga or 0,
            "save_pct": svpct or 0.0,
            "game_date": gdate,
        })

    features = {}
    all_rows_for_quantiles = []

    for pid, games in goalie_history.items():
        for i, g in enumerate(games):
            # Need at least 5 prior starts
            prior = games[:i]
            if len(prior) < 5:
                continue

            last10 = prior[-10:]
            last20 = prior[-20:] if len(prior) >= 10 else prior

            sa_avg_10 = np.mean([x["saves"] for x in last10])
            sa_avg_20 = np.mean([x["saves"] for x in last20])
            svpct_avg_10 = np.mean([x["save_pct"] for x in last10 if x["save_pct"] > 0])
            svpct_avg_20 = np.mean([x["save_pct"] for x in last20 if x["save_pct"] > 0])

            # Days rest — handle string dates from DB
            prev_date = prior[-1]["game_date"]
            gd = g["game_date"]
            if isinstance(gd, str):
                gd = date_type.fromisoformat(gd)
            if isinstance(prev_date, str):
                prev_date = date_type.fromisoformat(prev_date)
            days_rest = (gd - prev_date).days if prev_date else 3

            # Pull rate (GA > saves * 0.1 loosely — count games pulled)
            pull_rate_10 = 0  # placeholder — we don't track pulled perfectly
            starts_last_7d = sum(
                1 for x in prior[-7:]
                if (gd - (date_type.fromisoformat(x["game_date"])
                          if isinstance(x["game_date"], str)
                          else x["game_date"])).days <= 7
            )

            # Opponent team stats
            opp_tid = get_opponent(g["game_id"], g["team_id"])
            opp_stats = rolling_team_stats(opp_tid, g["game_date"]) if opp_tid else None
            own_stats = rolling_team_stats(g["team_id"], g["game_date"])

            if opp_stats is None or own_stats is None:
                continue

            feat = {
                "sa_avg_10": sa_avg_10,
                "sa_avg_20": sa_avg_20,
                "svpct_avg_10": svpct_avg_10,
                "svpct_avg_20": svpct_avg_20,
                "is_home": g["is_home"],
                "opp_team_sog_avg_10": opp_stats["sog_avg"],
                "days_rest": days_rest,
                "opp_corsi_pct_avg_10": opp_stats["corsi_pct_avg"],
                "opp_corsi_diff_avg_10": opp_stats["corsi_diff_avg"],
                "own_corsi_pct_avg_10": own_stats["corsi_pct_avg"],
                "pull_rate_10": pull_rate_10,
                "starts_last_7d": starts_last_7d,
                "opp_team_pp_opps_avg_10": opp_stats["pp_opps_avg"],
                "opp_puck_control_avg_10": opp_stats["puck_control_avg"],
                "target": g["saves"],
                "player_id": pid,
                "game_id": g["game_id"],
                "team_id": g["team_id"],
                "game_date": g["game_date"],
                "days_rest_raw": days_rest,
            }
            features[(pid, g["game_id"])] = feat
            all_rows_for_quantiles.append(feat)

    return features, all_rows_for_quantiles


def _train_model(features_list):
    """Train LightGBM regressor on all available data.

    Returns trained model.
    """
    if not HAS_LGB or not features_list:
        return None

    feature_cols = [
        "sa_avg_10", "sa_avg_20", "svpct_avg_10", "svpct_avg_20",
        "is_home", "opp_team_sog_avg_10", "days_rest",
        "opp_corsi_pct_avg_10", "opp_corsi_diff_avg_10",
        "own_corsi_pct_avg_10", "pull_rate_10", "starts_last_7d",
        "opp_team_pp_opps_avg_10",
    ]

    X = np.array([[f[c] for c in feature_cols] for f in features_list])
    y = np.array([f["target"] for f in features_list])

    model = lgb.LGBMRegressor(**LGB_PARAMS)
    model.fit(X, y)
    return model, feature_cols


def _compute_quantiles(all_rows):
    """Compute quantile thresholds for Corsi and puck control."""
    if not all_rows:
        return {}

    opp_corsi = [r["opp_corsi_pct_avg_10"] for r in all_rows]
    opp_corsi_diff = [r["opp_corsi_diff_avg_10"] for r in all_rows]
    opp_puck = [r["opp_puck_control_avg_10"] for r in all_rows]

    return {
        "opp_corsi_q25": np.percentile(opp_corsi, 25),
        "opp_corsi_q75": np.percentile(opp_corsi, 75),
        "opp_corsi_diff_q75": np.percentile(opp_corsi_diff, 75),
        "opp_puck_q75": np.percentile(opp_puck, 75),
    }


def _get_tonight_goalie_features(events):
    """Build feature vectors for tonight's probable starters.

    Uses the most recent goalie history to compute rolling features,
    then creates a 'projection' row for tonight's game.
    """
    conn = _get_conn()
    cur = conn.cursor()

    # Get team name → team_id mapping
    # DB has short names (Rangers, Avalanche), Odds API has full (New York Rangers)
    # Match by the last word(s) of the Odds API name to DB team_name
    cur.execute("SELECT team_id, team_name, tri_code FROM teams WHERE active=1")
    db_teams = cur.fetchall()
    team_map = {}  # Odds API full name → team_id
    tri_map = {}   # team_id → tri_code
    db_name_to_id = {}  # DB short name → team_id
    for tid, tname, tri in db_teams:
        db_name_to_id[tname.lower()] = tid
        tri_map[tid] = tri

    def _resolve_team(odds_api_name):
        """Map Odds API name like 'New York Rangers' to team_id."""
        # Try matching last word(s)
        parts = odds_api_name.lower().split()
        for i in range(len(parts)):
            candidate = " ".join(parts[i:])
            if candidate in db_name_to_id:
                return db_name_to_id[candidate]
        return None

    for ev in events:
        for key in ["home_team", "away_team"]:
            name = ev[key]
            if name not in team_map:
                tid = _resolve_team(name)
                if tid:
                    team_map[name] = tid

    conn.close()

    # Build full rolling features (we need the history)
    features, all_rows = _build_rolling_features()
    if not all_rows:
        return [], [], {}

    # Train model on all history
    result = _train_model(all_rows)
    if result is None:
        return [], [], {}
    model, feature_cols = result

    # Compute quantiles from all history
    quantiles = _compute_quantiles(all_rows)

    # For each team playing tonight, find their most recent starting goalie
    tonight_features = []
    conn = _get_conn()
    cur = conn.cursor()

    for ev in events:
        for team_name_key in ["home_team", "away_team"]:
            team_name = ev[team_name_key]
            tid = team_map.get(team_name)
            if not tid:
                continue

            is_home = 1 if team_name_key == "home_team" else 0

            # Find most recent starter for this team
            cur.execute("""
                SELECT gs.player_id, p.first_name || ' ' || p.last_name, g.game_date
                FROM goalie_stats gs
                JOIN games g ON gs.game_id = g.game_id
                JOIN players p ON gs.player_id = p.player_id
                WHERE gs.team_id = %s AND gs.started = 1
                ORDER BY g.game_date DESC
                LIMIT 1
            """, (tid,))
            row = cur.fetchone()
            if not row:
                continue

            goalie_pid, goalie_name, last_game_date = row

            # Get this goalie's recent history
            cur.execute("""
                SELECT gs.saves, gs.shots_against, gs.goals_against,
                       gs.save_pct, g.game_date
                FROM goalie_stats gs
                JOIN games g ON gs.game_id = g.game_id
                WHERE gs.player_id = %s AND gs.started = 1
                      AND gs.shots_against > 0
                ORDER BY g.game_date DESC
                LIMIT 20
            """, (goalie_pid,))
            history = cur.fetchall()
            if len(history) < 5:
                continue

            # Reverse to chronological order
            history = list(reversed(history))

            last10 = history[-10:]
            last20 = history

            sa_avg_10 = np.mean([h[0] for h in last10])
            sa_avg_20 = np.mean([h[0] for h in last20])
            svpct_avg_10 = np.mean([h[3] for h in last10 if h[3] and h[3] > 0])
            svpct_avg_20 = np.mean([h[3] for h in last20 if h[3] and h[3] > 0])

            from datetime import date as _date
            today = _date.today()
            lgd = last_game_date
            if isinstance(lgd, str):
                lgd = _date.fromisoformat(lgd)
            days_rest = (today - lgd).days if lgd else 3

            starts_last_7d = sum(
                1 for h in history
                if (today - (_date.fromisoformat(h[4]) if isinstance(h[4], str) else h[4])).days <= 7
            )

            # Opponent team ID
            opp_name = ev["away_team"] if team_name_key == "home_team" else ev["home_team"]
            opp_tid = team_map.get(opp_name)

            # Get opponent rolling stats
            opp_corsi_pct = None
            opp_corsi_diff = None
            opp_sog_avg = None
            opp_pp_opps = None
            opp_puck_control = None
            own_corsi_pct = None

            if opp_tid:
                cur.execute("""
                    SELECT gts.shots_attempted, gts.shots_on_goal,
                           gts.takeaways, gts.giveaways,
                           gts.power_play_opportunities,
                           g.game_date, gts.game_id
                    FROM game_team_stats gts
                    JOIN games g ON gts.game_id = g.game_id
                    WHERE gts.team_id = %s
                    ORDER BY g.game_date DESC
                    LIMIT 10
                """, (opp_tid,))
                opp_history = cur.fetchall()

                if len(opp_history) >= 3:
                    opp_sog_avg = np.mean([h[1] for h in opp_history if h[1]])

                    # Compute Corsi for opponent
                    corsi_pcts = []
                    corsi_diffs = []
                    for oh in opp_history:
                        opp_sa = oh[0] or 0
                        # Find the other team in this game
                        cur.execute("""
                            SELECT shots_attempted FROM game_team_stats
                            WHERE game_id = %s AND team_id != %s
                        """, (oh[6], opp_tid))
                        other = cur.fetchone()
                        if other and other[0]:
                            total = opp_sa + other[0]
                            if total > 0:
                                corsi_pcts.append(opp_sa / total)
                                corsi_diffs.append(opp_sa - other[0])

                    if corsi_pcts:
                        opp_corsi_pct = np.mean(corsi_pcts)
                        opp_corsi_diff = np.mean(corsi_diffs)

                    opp_pp_opps = np.mean([h[4] for h in opp_history if h[4] is not None])
                    opp_puck_control = np.mean(
                        [(h[2] or 0) - (h[3] or 0) for h in opp_history]
                    )

            # Own team Corsi
            if tid:
                cur.execute("""
                    SELECT gts.shots_attempted, gts.game_id
                    FROM game_team_stats gts
                    JOIN games g ON gts.game_id = g.game_id
                    WHERE gts.team_id = %s
                    ORDER BY g.game_date DESC
                    LIMIT 10
                """, (tid,))
                own_history = cur.fetchall()
                own_corsi_vals = []
                for oh in own_history:
                    cur.execute("""
                        SELECT shots_attempted FROM game_team_stats
                        WHERE game_id = %s AND team_id != %s
                    """, (oh[1], tid))
                    other = cur.fetchone()
                    if other and other[0]:
                        total = oh[0] + other[0]
                        if total > 0:
                            own_corsi_vals.append(oh[0] / total)
                if own_corsi_vals:
                    own_corsi_pct = np.mean(own_corsi_vals)

            if any(v is None for v in [opp_corsi_pct, opp_corsi_diff,
                                        opp_sog_avg, own_corsi_pct]):
                continue

            feat = {
                "sa_avg_10": sa_avg_10,
                "sa_avg_20": sa_avg_20,
                "svpct_avg_10": svpct_avg_10,
                "svpct_avg_20": svpct_avg_20,
                "is_home": is_home,
                "opp_team_sog_avg_10": opp_sog_avg,
                "days_rest": days_rest,
                "opp_corsi_pct_avg_10": opp_corsi_pct,
                "opp_corsi_diff_avg_10": opp_corsi_diff,
                "own_corsi_pct_avg_10": own_corsi_pct,
                "pull_rate_10": 0,
                "starts_last_7d": starts_last_7d,
                "opp_team_pp_opps_avg_10": opp_pp_opps or 0,
                "opp_puck_control_avg_10": opp_puck_control or 0,
                "goalie_name": goalie_name,
                "goalie_pid": goalie_pid,
                "team_name": team_name,
                "tri_code": tri_map.get(tid, "???"),
                "opp_name": opp_name,
                "game": f"{ev['away_team']} @ {ev['home_team']}",
                "event_id": ev["id"],
                "days_rest_raw": days_rest,
            }
            tonight_features.append(feat)

    conn.close()
    return tonight_features, model, feature_cols, quantiles


def _odds_to_implied(odds):
    """Convert American odds to implied probability."""
    if odds < 0:
        return abs(odds) / (abs(odds) + 100)
    else:
        return 100 / (odds + 100)


def _kelly_quarter(edge, odds):
    """Quarter Kelly bet sizing."""
    if odds < 0:
        b = 100 / abs(odds)
    else:
        b = odds / 100
    p = edge  # Our estimated true probability of winning
    q = 1 - p
    f_star = (b * p - q) / b
    if f_star <= 0:
        return 0, 0
    f_quarter = f_star / 4
    dollars = BANKROLL * f_quarter
    units = round(dollars / UNIT, 1)
    return units, round(dollars, 2)


def run_goalie_saves(best_odds, events):
    """Generate goalie saves picks using MF3, MF2, PF1 strategies.

    Args:
        best_odds: dict of best odds (unused for saves — we pull our own)
        events: list of event dicts from get_todays_events

    Returns:
        list of pick dicts ready for the pipeline
    """
    if not HAS_LGB:
        print("  ⚠️ LightGBM not available — skipping goalie saves")
        return []

    try:
        tonight_features, model, feature_cols, quantiles = _get_tonight_goalie_features(events)
    except Exception as e:
        print(f"  ⚠️ Error building goalie features: {e}")
        return []

    if not tonight_features:
        print("  No goalie features available")
        return []

    # Pull saves odds for tonight
    from pipeline.odds_pull import pull_player_props, get_best_odds as get_best

    saves_props = pull_player_props(events, markets=["player_total_saves"])
    if not saves_props:
        print("  ⚠️ No goalie saves odds available from Odds API")
        return []

    saves_best = get_best(saves_props)

    # Match goalies to their odds lines
    picks = []

    for feat in tonight_features:
        goalie_name = feat["goalie_name"]

        # Find matching odds — try exact name match
        matching_lines = {}
        for key, val in saves_best.items():
            player, market, side, line = key
            if market == "player_total_saves" and player == goalie_name:
                matching_lines[(side, line)] = val

        # Also try last-name match for fuzzy
        if not matching_lines:
            last_name = goalie_name.split()[-1]
            for key, val in saves_best.items():
                player, market, side, line = key
                if market == "player_total_saves" and last_name in player:
                    matching_lines[(side, line)] = val

        if not matching_lines:
            continue

        # Get the featured line (most common line across books)
        over_lines = {k: v for k, v in matching_lines.items() if k[0] == "Over"}
        under_lines = {k: v for k, v in matching_lines.items() if k[0] == "Under"}

        if not over_lines and not under_lines:
            continue

        # Use the line value from either side
        line_val = None
        for k in list(over_lines.keys()) + list(under_lines.keys()):
            line_val = k[1]
            break

        if line_val is None:
            continue

        # Predict saves
        import pandas as pd
        X = pd.DataFrame([[feat[c] for c in feature_cols]], columns=feature_cols)
        pred = model.predict(X)[0]
        model_gap = abs(pred - line_val)
        model_side = "under" if pred < line_val else "over"

        # === MF3: UNDER + Low Opponent Corsi ===
        if (model_side == "under"
            and feat["opp_corsi_pct_avg_10"] < quantiles["opp_corsi_q25"]):

            # MF3a: gap [1.0, 1.5)
            if 1.0 <= model_gap < 1.5 and under_lines:
                best_under = max(under_lines.values(), key=lambda x: x["odds"])
                implied = _odds_to_implied(best_under["odds"])
                # Our estimate: model says UNDER hits
                our_prob = 0.72  # MF3a historical: 72.3%
                edge = our_prob - implied
                if edge > 0.02:
                    units, dollars = _kelly_quarter(our_prob, best_under["odds"])
                    if units > 0:
                        picks.append({
                            "player": goalie_name,
                            "player_team": feat["tri_code"],
                            "game": feat["game"],
                            "event_id": feat["event_id"],
                            "strategy": "A: MF3a UNDER",
                            "bet": f"UNDER {line_val} saves",
                            "odds": best_under["odds"],
                            "book": best_under["book"],
                            "book_title": best_under["book_title"],
                            "edge": edge,
                            "confidence": "🟢 HIGH" if edge >= 0.08 else "🟡 MEDIUM",
                            "units": units,
                            "dollars": dollars,
                            "pred": round(pred, 1),
                            "line": line_val,
                            "gap": round(model_gap, 1),
                            "sub_strategy": "MF3a",
                        })

            # Skip dead zone [1.5, 2.5) — 53.4% win, -13.3% ROI

            # MF3b: gap ≥ 2.5
            if model_gap >= 2.5 and under_lines:
                best_under = max(under_lines.values(), key=lambda x: x["odds"])
                implied = _odds_to_implied(best_under["odds"])
                our_prob = 0.65  # MF3b historical: 65.2%
                edge = our_prob - implied
                if edge > 0.02:
                    units, dollars = _kelly_quarter(our_prob, best_under["odds"])
                    if units > 0:
                        # Check if we already added MF3a for this goalie
                        already = any(p["player"] == goalie_name
                                      and p["sub_strategy"] == "MF3a" for p in picks)
                        if not already:
                            picks.append({
                                "player": goalie_name,
                                "player_team": feat["tri_code"],
                                "game": feat["game"],
                                "event_id": feat["event_id"],
                                "strategy": "A: MF3b UNDER",
                                "bet": f"UNDER {line_val} saves",
                                "odds": best_under["odds"],
                                "book": best_under["book"],
                                "book_title": best_under["book_title"],
                                "edge": edge,
                                "confidence": "🟢 HIGH" if model_gap >= 3.0 else "🟡 MEDIUM",
                                "units": units,
                                "dollars": dollars,
                                "pred": round(pred, 1),
                                "line": line_val,
                                "gap": round(model_gap, 1),
                                "sub_strategy": "MF3b",
                            })

        # === MF2: UNDER + Back-to-Back ===
        if (model_side == "under"
            and model_gap >= 2.0
            and feat["days_rest_raw"] <= 1
            and under_lines):

            best_under = max(under_lines.values(), key=lambda x: x["odds"])
            implied = _odds_to_implied(best_under["odds"])
            our_prob = 0.64  # MF2 historical: 64.0%
            edge = our_prob - implied
            if edge > 0.02:
                units, dollars = _kelly_quarter(our_prob, best_under["odds"])
                if units > 0:
                    # MF2 is independent signal — can stack with MF3
                    already_mf2 = any(p["player"] == goalie_name
                                      and "MF2" in p["sub_strategy"] for p in picks)
                    if not already_mf2:
                        picks.append({
                            "player": goalie_name,
                            "player_team": feat["tri_code"],
                            "game": feat["game"],
                            "event_id": feat["event_id"],
                            "strategy": "A: MF2 UNDER (B2B)",
                            "bet": f"UNDER {line_val} saves",
                            "odds": best_under["odds"],
                            "book": best_under["book"],
                            "book_title": best_under["book_title"],
                            "edge": edge,
                            "confidence": "🟢 HIGH" if model_gap >= 2.5 else "🟡 MEDIUM",
                            "units": units,
                            "dollars": dollars,
                            "pred": round(pred, 1),
                            "line": line_val,
                            "gap": round(model_gap, 1),
                            "sub_strategy": "MF2",
                        })

        # === PF1: OVER + Triple Corsi Filter ===
        if (feat["opp_corsi_pct_avg_10"] > quantiles["opp_corsi_q75"]
            and feat["opp_corsi_diff_avg_10"] > quantiles["opp_corsi_diff_q75"]
            and feat["opp_puck_control_avg_10"] > quantiles["opp_puck_q75"]
            and over_lines):

            best_over = max(over_lines.values(), key=lambda x: x["odds"])
            implied = _odds_to_implied(best_over["odds"])
            our_prob = 0.59  # PF1 historical: 59.2%
            edge = our_prob - implied
            if edge > 0.02:
                units, dollars = _kelly_quarter(our_prob, best_over["odds"])
                if units > 0:
                    picks.append({
                        "player": goalie_name,
                        "player_team": feat["tri_code"],
                        "game": feat["game"],
                        "event_id": feat["event_id"],
                        "strategy": "A: PF1 OVER",
                        "bet": f"OVER {line_val} saves",
                        "odds": best_over["odds"],
                        "book": best_over["book"],
                        "book_title": best_over["book_title"],
                        "edge": edge,
                        "confidence": "🟡 MEDIUM" if edge >= 0.05 else "⚪ LOW",
                        "units": units,
                        "dollars": dollars,
                        "pred": round(pred, 1),
                        "line": line_val,
                        "gap": round(model_gap, 1),
                        "sub_strategy": "PF1",
                    })

    # Sort by edge descending
    picks.sort(key=lambda p: p["edge"], reverse=True)

    # Deduplicate — one pick per goalie (take highest edge)
    seen_goalies = set()
    deduped = []
    for p in picks:
        if p["player"] not in seen_goalies:
            seen_goalies.add(p["player"])
            deduped.append(p)

    return deduped


if __name__ == "__main__":
    print("Building rolling features...")
    features, all_rows = _build_rolling_features()
    print(f"Feature rows: {len(all_rows)}")
    if all_rows:
        quantiles = _compute_quantiles(all_rows)
        print(f"Quantiles: {quantiles}")
        result = _train_model(all_rows)
        if result:
            model, cols = result
            print(f"Model trained on {len(all_rows)} rows, {len(cols)} features")
