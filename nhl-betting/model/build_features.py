#!/usr/bin/env python3
"""
Phase 1: Feature Engineering
Build the feature matrix for goalie saves prediction.
"""

import numpy as np
import pandas as pd
import psycopg2

DB_CONN = "postgresql://connorrainey@localhost:5432/nhl_betting"


def load_tables():
    """Load all needed tables into DataFrames."""
    conn = psycopg2.connect(DB_CONN)

    tables = {
        'saves_odds': "SELECT * FROM saves_odds WHERE book_name = 'consensus'",
        'goalie_stats': "SELECT * FROM goalie_stats",
        'games': "SELECT * FROM games WHERE home_score IS NOT NULL",
        'game_team_stats': "SELECT * FROM game_team_stats",
        'goalie_strength': "SELECT * FROM goalie_saves_by_strength",
        'goalie_advanced': "SELECT * FROM goalie_advanced",
        'goalie_starts': "SELECT * FROM goalie_starts",
        'lineup_absences': "SELECT * FROM lineup_absences",
        'period_scores': "SELECT * FROM period_scores",
        'players': "SELECT * FROM players",
        'schedules': "SELECT game_id, game_date, home_team_id, away_team_id FROM schedules",
    }

    dfs = {}
    for name, query in tables.items():
        dfs[name] = pd.read_sql(query, conn)
        print(f"  Loaded {name}: {len(dfs[name])} rows")

    conn.close()
    return dfs


def build_goalie_rolling_features(goalie_stats, players, games, window_sizes=[5, 10, 20]):
    """Build rolling goalie performance features."""
    # Merge goalie stats with game dates
    gs = goalie_stats.merge(
        games[['game_id', 'game_date', 'home_team_id', 'away_team_id']],
        on='game_id', how='inner'
    )
    gs = gs.sort_values(['player_id', 'game_date'])

    features = []
    for pid, group in gs.groupby('player_id'):
        group = group.copy().sort_values('game_date')

        for w in window_sizes:
            group[f'saves_avg_{w}'] = group['saves'].rolling(w, min_periods=3).mean().shift(1)
            group[f'sa_avg_{w}'] = group['shots_against'].rolling(w, min_periods=3).mean().shift(1)
            group[f'svpct_avg_{w}'] = group['save_pct'].rolling(w, min_periods=3).mean().shift(1)
            group[f'ga_avg_{w}'] = group['goals_against'].rolling(w, min_periods=3).mean().shift(1)

        # Season-to-date
        group['saves_season_avg'] = group['saves'].expanding(min_periods=3).mean().shift(1)
        group['svpct_season_avg'] = group['save_pct'].expanding(min_periods=3).mean().shift(1)

        # Games started in last 7 and 14 days
        group['game_date_dt'] = pd.to_datetime(group['game_date'])
        for days in [7, 14, 30]:
            starts = []
            dates = group['game_date_dt'].values
            for i in range(len(dates)):
                cutoff = dates[i] - pd.Timedelta(days=days)
                count = ((dates[:i] >= cutoff) & (dates[:i] < dates[i])).sum()
                starts.append(count)
            group[f'starts_last_{days}d'] = starts

        # Days since last start
        group['days_rest'] = group['game_date_dt'].diff().dt.days.fillna(7)

        features.append(group)

    result = pd.concat(features, ignore_index=True)
    return result


def build_team_rolling_features(game_team_stats, games, window_sizes=[5, 10, 20]):
    """Build rolling team offensive/defensive features."""
    gts = game_team_stats.merge(
        games[['game_id', 'game_date']], on='game_id', how='inner'
    )
    gts = gts.sort_values(['team_id', 'game_date'])

    features = []
    for tid, group in gts.groupby('team_id'):
        group = group.copy().sort_values('game_date')

        for w in window_sizes:
            group[f'team_sog_avg_{w}'] = group['shots_on_goal'].rolling(w, min_periods=3).mean().shift(1)
            group[f'team_sa_avg_{w}'] = group['shots_attempted'].rolling(w, min_periods=3).mean().shift(1)
            group[f'team_pp_opps_avg_{w}'] = group['power_play_opportunities'].rolling(w, min_periods=3).mean().shift(1)
            group[f'team_hits_avg_{w}'] = group['hits'].rolling(w, min_periods=3).mean().shift(1)

        group['team_sog_season_avg'] = group['shots_on_goal'].expanding(min_periods=3).mean().shift(1)

        features.append(group)

    result = pd.concat(features, ignore_index=True)
    return result


def build_strength_features(goalie_strength, games):
    """Build EV/PP/SH save split features."""
    gs = goalie_strength.copy()
    # goalie_strength already has game_date column
    if 'game_date' not in gs.columns:
        gs = gs.merge(
            games[['game_id', 'game_date']],
            on='game_id', how='inner'
        )
    gs = gs.sort_values(['player_id', 'game_date'])

    features = []
    for pid, group in gs.groupby('player_id'):
        group = group.copy().sort_values('game_date')

        for w in [10, 20]:
            group[f'ev_svpct_avg_{w}'] = group['ev_save_pct'].rolling(w, min_periods=3).mean().shift(1)
            group[f'pp_shots_avg_{w}'] = group['pp_shots'].rolling(w, min_periods=3).mean().shift(1)
            group[f'sh_shots_avg_{w}'] = group['sh_shots'].rolling(w, min_periods=3).mean().shift(1)
            group[f'ev_shots_avg_{w}'] = group['ev_shots'].rolling(w, min_periods=3).mean().shift(1)

        features.append(group)

    result = pd.concat(features, ignore_index=True)
    return result


def build_pull_features(goalie_advanced, goalie_stats, games):
    """Build goalie pull prediction features."""
    gs = goalie_stats.merge(
        games[['game_id', 'game_date', 'home_team_id', 'away_team_id', 'home_score', 'away_score']],
        on='game_id', how='inner'
    )

    # Detect pulls: goalie started but played < 55 min (regulation is 60)
    # Use time_on_ice from goalie_advanced if available, else infer from saves pattern
    ga = goalie_advanced[['game_id', 'player_id', 'games_started', 'complete_games', 'incomplete_games', 'time_on_ice']].copy()

    gs = gs.merge(ga, on=['game_id', 'player_id'], how='left')

    # Mark pulls: started but incomplete
    gs['was_pulled'] = ((gs['games_started'] == 1) & (gs['incomplete_games'] == 1)).astype(int)
    # Also flag via goals against - pulled goalies typically allow 4+
    gs['high_ga'] = (gs['goals_against'] >= 4).astype(int)

    gs = gs.sort_values(['player_id', 'game_date'])

    features = []
    for pid, group in gs.groupby('player_id'):
        group = group.copy().sort_values('game_date')

        # Rolling pull rate
        for w in [10, 20]:
            group[f'pull_rate_{w}'] = group['was_pulled'].rolling(w, min_periods=3).mean().shift(1)
            group[f'high_ga_rate_{w}'] = group['high_ga'].rolling(w, min_periods=3).mean().shift(1)

        group['pull_rate_season'] = group['was_pulled'].expanding(min_periods=3).mean().shift(1)

        features.append(group)

    result = pd.concat(features, ignore_index=True)
    return result


def build_rest_and_b2b(schedules, games):
    """Derive back-to-back and rest day features for teams."""
    sched = schedules.copy()
    sched['game_date'] = pd.to_datetime(sched['game_date'])

    # Build for each team
    team_games = []
    for col, team_col in [('home_team_id', 'home_team_id'), ('away_team_id', 'away_team_id')]:
        subset = sched[['game_id', 'game_date', col]].copy()
        subset.columns = ['game_id', 'game_date', 'team_id']
        team_games.append(subset)

    team_games = pd.concat(team_games, ignore_index=True)
    team_games = team_games.sort_values(['team_id', 'game_date'])

    features = []
    for tid, group in team_games.groupby('team_id'):
        group = group.copy().sort_values('game_date')
        group['team_rest_days'] = group['game_date'].diff().dt.days.fillna(3)
        group['team_b2b'] = (group['team_rest_days'] <= 1).astype(int)
        # 3-in-4 not needed, b2b is sufficient
        features.append(group)

    result = pd.concat(features, ignore_index=True)
    # We need this per game_id + team_id
    result = result[['game_id', 'team_id', 'team_rest_days', 'team_b2b']].copy()
    return result


def build_feature_matrix(dfs):
    """Assemble the full feature matrix."""
    print("\nBuilding goalie rolling features...")
    goalie_feats = build_goalie_rolling_features(dfs['goalie_stats'], dfs['players'], dfs['games'])

    print("Building team rolling features...")
    team_feats = build_team_rolling_features(dfs['game_team_stats'], dfs['games'])

    print("Building strength split features...")
    strength_feats = build_strength_features(dfs['goalie_strength'], dfs['games'])

    print("Building pull features...")
    pull_feats = build_pull_features(dfs['goalie_advanced'], dfs['goalie_stats'], dfs['games'])

    print("Building rest/B2B features...")
    rest_feats = build_rest_and_b2b(dfs['schedules'], dfs['games'])

    # Start with saves_odds as the base (consensus lines only)
    odds = dfs['saves_odds'].copy()
    odds = odds[odds['line'] >= 10]  # filter anomalous lines

    # We need to match odds to goalie_stats via player_name + event_date
    # goalie_feats has player_id + game_date, odds has player_name + event_date
    # Join via players table for name -> player_id mapping
    players = dfs['players']
    players['full_name'] = players['first_name'] + ' ' + players['last_name']
    name_to_id = players.set_index('full_name')['player_id'].to_dict()

    odds['player_id'] = odds['player_name'].map(name_to_id)
    print(f"  Odds matched to player_id: {odds['player_id'].notna().sum()}/{len(odds)}")
    odds = odds.dropna(subset=['player_id'])
    odds['player_id'] = odds['player_id'].astype(int)

    # Match odds to games via event_date
    games = dfs['games'].copy()
    games['game_date_str'] = games['game_date'].astype(str)

    # For each odds row, find the game where this goalie played on this date
    goalie_game_map = goalie_feats[['player_id', 'game_id', 'game_date']].copy()
    goalie_game_map['game_date_str'] = goalie_game_map['game_date'].astype(str)

    # Merge odds with goalie game mapping
    matrix = odds.merge(
        goalie_game_map[['player_id', 'game_id', 'game_date_str']],
        left_on=['player_id', 'event_date'],
        right_on=['player_id', 'game_date_str'],
        how='inner'
    )
    print(f"  Odds matched to games: {len(matrix)}")

    # Add actual saves (target)
    gs = dfs['goalie_stats'][['game_id', 'player_id', 'saves', 'shots_against', 'goals_against', 'save_pct']].copy()
    matrix = matrix.merge(gs, on=['game_id', 'player_id'], how='inner')
    print(f"  With actual saves: {len(matrix)}")

    # Add goalie rolling features
    goalie_feat_cols = [c for c in goalie_feats.columns if c.startswith(('saves_avg', 'sa_avg', 'svpct_avg', 'ga_avg', 'saves_season', 'svpct_season', 'starts_last', 'days_rest'))]
    matrix = matrix.merge(
        goalie_feats[['game_id', 'player_id'] + goalie_feat_cols],
        on=['game_id', 'player_id'], how='left'
    )

    # Add strength features
    strength_feat_cols = [c for c in strength_feats.columns if c.endswith(('_10', '_20')) and c.startswith(('ev_', 'pp_', 'sh_'))]
    matrix = matrix.merge(
        strength_feats[['game_id', 'player_id'] + strength_feat_cols],
        on=['game_id', 'player_id'], how='left'
    )

    # Add pull features
    pull_feat_cols = [c for c in pull_feats.columns if c.startswith(('pull_rate', 'high_ga_rate', 'was_pulled'))]
    matrix = matrix.merge(
        pull_feats[['game_id', 'player_id'] + pull_feat_cols],
        on=['game_id', 'player_id'], how='left'
    )

    # Determine opponent team for each goalie
    game_info = dfs['games'][['game_id', 'home_team_id', 'away_team_id']].copy()
    goalie_team = dfs['goalie_stats'][['game_id', 'player_id', 'team_id']].copy()
    matrix = matrix.merge(goalie_team[['game_id', 'player_id', 'team_id']], on=['game_id', 'player_id'], how='left')
    matrix = matrix.merge(game_info, on='game_id', how='left')
    matrix['opponent_team_id'] = np.where(
        matrix['team_id'] == matrix['home_team_id'],
        matrix['away_team_id'],
        matrix['home_team_id']
    )
    matrix['is_home'] = (matrix['team_id'] == matrix['home_team_id']).astype(int)

    # Add opponent team features (shots they generate)
    opp_team_feats = team_feats.copy()
    opp_feat_cols = [c for c in opp_team_feats.columns if c.startswith('team_') and c != 'team_id']
    opp_rename = {c: f'opp_{c}' for c in opp_feat_cols}
    opp_team_feats = opp_team_feats.rename(columns=opp_rename)
    opp_feat_cols_renamed = list(opp_rename.values())

    matrix = matrix.merge(
        opp_team_feats[['game_id', 'team_id'] + opp_feat_cols_renamed],
        left_on=['game_id', 'opponent_team_id'],
        right_on=['game_id', 'team_id'],
        how='left',
        suffixes=('', '_opp')
    )

    # Add own team features (shots they allow = defensive quality)
    own_team_feats = team_feats.copy()
    own_feat_cols = [c for c in own_team_feats.columns if c.startswith('team_') and c != 'team_id']
    own_rename = {c: f'own_{c}' for c in own_feat_cols}
    own_team_feats = own_team_feats.rename(columns=own_rename)
    own_feat_cols_renamed = list(own_rename.values())

    matrix = matrix.merge(
        own_team_feats[['game_id', 'team_id'] + own_feat_cols_renamed],
        left_on=['game_id', 'team_id'],
        right_on=['game_id', 'team_id'],
        how='left',
        suffixes=('', '_own')
    )

    # Add lineup absences — opponent absences (their missing D = fewer blocks = more shots on our goalie)
    # and own team absences (our missing players = more time in own zone)
    abs_df = dfs['lineup_absences'].copy()

    # Opponent defensive absences
    opp_abs = abs_df[['game_id', 'team_id', 'def_missing', 'def_missing_toi', 'fwd_missing', 'fwd_missing_toi', 'total_missing', 'total_missing_toi']].copy()
    opp_abs_rename = {c: f'opp_{c}' for c in opp_abs.columns if c not in ('game_id', 'team_id')}
    opp_abs = opp_abs.rename(columns=opp_abs_rename)

    matrix = matrix.merge(
        opp_abs,
        left_on=['game_id', 'opponent_team_id'],
        right_on=['game_id', 'team_id'],
        how='left',
        suffixes=('', '_oppabs')
    )

    # Own team absences
    own_abs = abs_df[['game_id', 'team_id', 'def_missing', 'def_missing_toi', 'fwd_missing', 'total_missing_toi']].copy()
    own_abs_rename = {c: f'own_{c}' for c in own_abs.columns if c not in ('game_id', 'team_id')}
    own_abs = own_abs.rename(columns=own_abs_rename)

    matrix = matrix.merge(
        own_abs,
        left_on=['game_id', 'team_id'],
        right_on=['game_id', 'team_id'],
        how='left',
        suffixes=('', '_ownabs')
    )

    # Add rest/B2B for opponent
    matrix = matrix.merge(
        rest_feats.rename(columns={'team_rest_days': 'opp_rest_days', 'team_b2b': 'opp_b2b'}),
        left_on=['game_id', 'opponent_team_id'],
        right_on=['game_id', 'team_id'],
        how='left',
        suffixes=('', '_opprest')
    )

    # Line movement feature
    matrix['line_movement'] = matrix['line'] - matrix['opening_line']

    # Over/under result
    matrix['went_over'] = (matrix['saves'] > matrix['line']).astype(int)
    matrix['went_under'] = (matrix['saves'] < matrix['line']).astype(int)
    matrix['save_diff'] = matrix['saves'] - matrix['line']

    # Clean up
    matrix['event_date'] = pd.to_datetime(matrix['event_date'])
    matrix = matrix.sort_values('event_date')

    print(f"\nFinal feature matrix: {len(matrix)} rows, {len(matrix.columns)} columns")
    print(f"Date range: {matrix['event_date'].min()} to {matrix['event_date'].max()}")
    print(f"Over rate: {matrix['went_over'].mean():.3f}")
    print(f"Under rate: {matrix['went_under'].mean():.3f}")
    print(f"Push rate: {1 - matrix['went_over'].mean() - matrix['went_under'].mean():.3f}")

    return matrix


def get_feature_columns(matrix):
    """Return the list of feature columns for modeling."""
    exclude = {
        'game_id', 'player_id', 'team_id', 'home_team_id', 'away_team_id',
        'opponent_team_id', 'event_id', 'event_date', 'game_date', 'game_date_str',
        'game_date_dt', 'player_name', 'player_team', 'home_team', 'away_team',
        'book_id', 'book_name', 'opening_created', 'updated_at', 'scraped_at',
        'is_best', 'bp_player_id',
        # Targets / leakage
        'saves', 'shots_against', 'goals_against', 'save_pct',
        'went_over', 'went_under', 'save_diff', 'was_pulled',
        # ID columns with _opp, _own suffixes
        'team_id_opp', 'team_id_own', 'team_id_oppabs', 'team_id_ownabs', 'team_id_opprest',
    }

    feature_cols = [c for c in matrix.columns if c not in exclude and matrix[c].dtype in ('float64', 'int64', 'int32', 'float32', 'bool')]
    return feature_cols


if __name__ == '__main__':
    print("Loading data...")
    dfs = load_tables()

    print("\nBuilding feature matrix...")
    matrix = build_feature_matrix(dfs)

    feature_cols = get_feature_columns(matrix)
    print(f"\nFeature columns ({len(feature_cols)}):")
    for c in sorted(feature_cols):
        print(f"  {c}")

    # Save
    matrix.to_pickle('/Users/connorrainey/nhc-capital/nhl-betting/model/feature_matrix.pkl')
    print("\nSaved to model/feature_matrix.pkl")
