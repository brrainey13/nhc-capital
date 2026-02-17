"""
Dr. Strange Edge Finder
Brute-force search across all features × all bettable outcomes × all conditions.
Finds any combination that produces meaningful +EV across multiple seasons.

Run 20+ iterations with different random seeds, feature combos, and thresholds.
"""
import json
import os
import subprocess
from datetime import datetime

import numpy as np
import pandas as pd

PSQL = '/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql'
DB = 'nhl_betting'
RESULTS_FILE = os.path.join(os.path.dirname(__file__), 'dr_strange_results.json')

def psql_copy(query, path):
    subprocess.run([PSQL, '-d', DB, '-c', f"COPY ({query}) TO '{path}' WITH CSV HEADER"],
                   capture_output=True, text=True)

def load_all_data():
    """Load every table we have into a unified game-level dataset."""
    print("Loading all data...")

    # Games
    psql_copy("SELECT game_id, game_date, season, home_team_id, away_team_id FROM games", '/tmp/ds_games.csv')
    games = pd.read_csv('/tmp/ds_games.csv')
    games['game_date'] = pd.to_datetime(games['game_date'])
    games['dow'] = games['game_date'].dt.dayofweek
    games['month'] = games['game_date'].dt.month
    games['game_num'] = games.groupby(['home_team_id','season']).cumcount() + 1

    # Team stats (both teams per game)
    psql_copy("""SELECT game_id, team_id, is_home, score, shots_on_goal, shots_attempted,
                 power_play_goals, power_play_opportunities, pim, hits, blocked_shots,
                 faceoff_win_pct, giveaways, takeaways, won FROM game_team_stats""", '/tmp/ds_ts.csv')
    ts = pd.read_csv('/tmp/ds_ts.csv')

    # Absences
    psql_copy("""SELECT game_id, team_id, def_missing, def_missing_toi, fwd_missing,
                 fwd_missing_toi, total_missing, total_missing_toi FROM lineup_absences""", '/tmp/ds_abs.csv')
    ab = pd.read_csv('/tmp/ds_abs.csv')

    # Goalie stats
    psql_copy("""SELECT gs.game_id, gs.player_id, gs.team_id, gs.saves, gs.shots_against,
                 gs.goals_against, gs.save_pct, gs.toi_minutes, gs.started,
                 p.first_name || ' ' || p.last_name as goalie_name
                 FROM goalie_stats gs JOIN players p ON gs.player_id = p.player_id
                 WHERE gs.shots_against > 0""", '/tmp/ds_gs.csv')
    gs = pd.read_csv('/tmp/ds_gs.csv')

    # Period scores
    psql_copy("""SELECT game_id, team_id, period_number as period, goals FROM period_scores WHERE period_number <= 3""", '/tmp/ds_ps.csv')
    ps = pd.read_csv('/tmp/ds_ps.csv')

    # Standings (for team strength context)
    psql_copy("""SELECT DISTINCT ON (team_id, season) team_id, season, wins, losses, points, goal_diff, goals_for, goals_against
                 FROM standings ORDER BY team_id, season, standing_date DESC""", '/tmp/ds_stand.csv')
    stand = pd.read_csv('/tmp/ds_stand.csv')

    # Saves odds (for line comparison)
    psql_copy("""SELECT event_date, player_name, line, over_odds, under_odds, book_name
                 FROM saves_odds WHERE book_name = 'consensus'""", '/tmp/ds_odds.csv')
    odds = pd.read_csv('/tmp/ds_odds.csv')

    print(f"  Games: {len(games)}, TeamStats: {len(ts)}, Absences: {len(ab)}")
    print(f"  GoalieStats: {len(gs)}, PeriodScores: {len(ps)}, Standings: {len(stand)}")

    return games, ts, ab, gs, ps, stand, odds

def build_game_features(games, ts, ab, gs, ps, stand):
    """Build a comprehensive game-level feature matrix with rolling stats."""
    print("Building features...")

    # For each team-game: own stats + opponent stats + own absences + opp absences
    # Merge team stats with games
    tsg = ts.merge(games[['game_id','game_date','season','home_team_id','away_team_id','dow','month','game_num']], on='game_id')
    tsg['opp_team_id'] = np.where(tsg['team_id']==tsg['home_team_id'], tsg['away_team_id'], tsg['home_team_id'])

    # Own team absences
    tsg = tsg.merge(ab, on=['game_id','team_id'], how='left', suffixes=('',''))
    # Opp team absences
    opp_ab = ab.rename(columns={c: f'opp_{c}' if c not in ['game_id','team_id'] else c for c in ab.columns})
    tsg = tsg.merge(opp_ab, left_on=['game_id','opp_team_id'], right_on=['game_id','team_id'],
                    how='left', suffixes=('','_opp_dup'))
    # Clean up duplicate team_id
    if 'team_id_opp_dup' in tsg.columns:
        tsg.drop('team_id_opp_dup', axis=1, inplace=True)

    # Opponent team stats (for this game)
    opp_ts = ts.rename(columns={c: f'opp_{c}' if c not in ['game_id','team_id'] else c for c in ts.columns})
    tsg = tsg.merge(opp_ts, left_on=['game_id','opp_team_id'], right_on=['game_id','team_id'],
                    how='left', suffixes=('','_opp2'))
    if 'team_id_opp2' in tsg.columns:
        tsg.drop('team_id_opp2', axis=1, inplace=True)

    tsg = tsg.sort_values(['team_id','game_date']).reset_index(drop=True)

    # Rolling features (SHIFTED - only prior games, no leakage)
    roll_cols = ['shots_on_goal','shots_attempted','hits','blocked_shots','pim',
                 'giveaways','takeaways','score','power_play_opportunities']

    for col in roll_cols:
        if col in tsg.columns:
            for w in [5, 10]:
                tsg[f'{col}_avg_{w}'] = tsg.groupby('team_id')[col].transform(
                    lambda x: x.rolling(w, min_periods=3).mean().shift(1))

    # Opp rolling features
    opp_roll = ['opp_shots_on_goal','opp_hits','opp_blocked_shots','opp_score','opp_power_play_opportunities']
    for col in opp_roll:
        if col in tsg.columns:
            for w in [5, 10]:
                tsg[f'{col}_avg_{w}'] = tsg.groupby('team_id')[col].transform(
                    lambda x: x.rolling(w, min_periods=3).mean().shift(1))

    # Absence rolling
    for col in ['def_missing','def_missing_toi','total_missing','total_missing_toi',
                'opp_def_missing','opp_def_missing_toi','opp_total_missing','opp_total_missing_toi']:
        if col in tsg.columns:
            tsg[f'{col}_avg_5'] = tsg.groupby('team_id')[col].transform(
                lambda x: x.rolling(5, min_periods=1).mean().shift(1))

    # Days rest
    tsg['days_rest'] = tsg.groupby('team_id')['game_date'].diff().dt.days
    tsg['is_b2b'] = (tsg['days_rest'] == 1).astype(int)

    # Win streak
    tsg['win_streak'] = tsg.groupby('team_id')['won'].transform(
        lambda x: x.shift(1).rolling(10, min_periods=1).sum())

    # Period goals (pivot: goals in P1, P2, P3)
    p1 = ps[ps['period']==1].rename(columns={'goals':'p1_goals'})
    p2 = ps[ps['period']==2].rename(columns={'goals':'p2_goals'})
    p3 = ps[ps['period']==3].rename(columns={'goals':'p3_goals'})

    for pn, pdf in [('p1_goals',p1),('p2_goals',p2),('p3_goals',p3)]:
        tsg = tsg.merge(pdf[['game_id','team_id',pn]], on=['game_id','team_id'], how='left')

    # Opponent period goals
    for pn, pdf in [('opp_p1_goals',p1.rename(columns={'p1_goals':'opp_p1_goals'})),
                     ('opp_p2_goals',p2.rename(columns={'p2_goals':'opp_p2_goals'})),
                     ('opp_p3_goals',p3.rename(columns={'p3_goals':'opp_p3_goals'}))]:
        tsg = tsg.merge(pdf[['game_id','team_id',pn]], left_on=['game_id','opp_team_id'],
                       right_on=['game_id','team_id'], how='left', suffixes=('','_pdrop'))
        if 'team_id_pdrop' in tsg.columns:
            tsg.drop('team_id_pdrop', axis=1, inplace=True)

    print(f"  Feature matrix: {len(tsg)} rows, {len(tsg.columns)} columns")
    return tsg

def define_targets(tsg):
    """Define all bettable outcomes we can test."""
    targets = {}

    # Team-level targets
    targets['team_sog_over_28.5'] = (tsg['shots_on_goal'] > 28.5).astype(int)
    targets['team_sog_over_29.5'] = (tsg['shots_on_goal'] > 29.5).astype(int)
    targets['team_sog_over_30.5'] = (tsg['shots_on_goal'] > 30.5).astype(int)
    targets['team_sog_over_31.5'] = (tsg['shots_on_goal'] > 31.5).astype(int)

    # Dynamic: team SOG over season-rolling average
    tsg['_sog_season_avg'] = tsg.groupby(['team_id','season'])['shots_on_goal'].transform(
        lambda x: x.expanding().mean().shift(1))
    targets['team_sog_over_season_avg'] = (tsg['shots_on_goal'] > tsg['_sog_season_avg']).astype(int)

    # Team goals
    targets['team_goals_over_2.5'] = (tsg['score'] > 2.5).astype(int)
    targets['team_goals_over_3.5'] = (tsg['score'] > 3.5).astype(int)

    # Total game goals
    targets['total_goals_over_5.5'] = ((tsg['score'] + tsg.get('opp_score', 0)) > 5.5).astype(int) if 'opp_score' in tsg.columns else None
    targets['total_goals_over_6.5'] = ((tsg['score'] + tsg.get('opp_score', 0)) > 6.5).astype(int) if 'opp_score' in tsg.columns else None

    # Team hits
    targets['team_hits_over_20.5'] = (tsg['hits'] > 20.5).astype(int)
    targets['team_hits_over_24.5'] = (tsg['hits'] > 24.5).astype(int)

    # Team blocked shots
    targets['team_blocks_over_12.5'] = (tsg['blocked_shots'] > 12.5).astype(int)
    targets['team_blocks_over_14.5'] = (tsg['blocked_shots'] > 14.5).astype(int)

    # PIM
    targets['team_pim_over_6.5'] = (tsg['pim'] > 6.5).astype(int)
    targets['team_pim_over_8.5'] = (tsg['pim'] > 8.5).astype(int)

    # Period-specific
    if 'p1_goals' in tsg.columns:
        targets['p1_goals_over_0.5'] = (tsg['p1_goals'] > 0.5).astype(int)
        targets['p1_goals_over_1.5'] = (tsg['p1_goals'] > 1.5).astype(int)
        targets['total_p1_goals_over_1.5'] = ((tsg.get('p1_goals',0) + tsg.get('opp_p1_goals',0)) > 1.5).astype(int)

    # Team wins (moneyline)
    targets['team_win'] = tsg['won'].astype(int)

    # Shots attempted
    if 'shots_attempted' in tsg.columns:
        targets['team_sa_over_50.5'] = (tsg['shots_attempted'] > 50.5).astype(int)
        targets['team_sa_over_55.5'] = (tsg['shots_attempted'] > 55.5).astype(int)

    # Remove None targets
    targets = {k: v for k, v in targets.items() if v is not None}

    return targets

def define_conditions(tsg):
    """Define all possible filtering conditions (pre-game knowable)."""
    conditions = {}

    # D absence conditions
    for thresh in [1, 2, 3, 4]:
        if 'opp_def_missing' in tsg.columns:
            conditions[f'opp_{thresh}+D_missing'] = tsg['opp_def_missing'] >= thresh
        if 'def_missing' in tsg.columns:
            conditions[f'own_{thresh}+D_missing'] = tsg['def_missing'] >= thresh

    # TOI absence conditions
    for thresh in [20, 30, 40, 50, 60]:
        if 'opp_def_missing_toi' in tsg.columns:
            conditions[f'opp_D_toi_{thresh}+'] = tsg['opp_def_missing_toi'] >= thresh
        if 'def_missing_toi' in tsg.columns:
            conditions[f'own_D_toi_{thresh}+'] = tsg['def_missing_toi'] >= thresh
        if 'opp_total_missing_toi' in tsg.columns:
            conditions[f'opp_total_toi_{thresh}+'] = tsg['opp_total_missing_toi'] >= thresh

    # Schedule conditions
    if 'is_b2b' in tsg.columns:
        conditions['is_b2b'] = tsg['is_b2b'] == 1
        conditions['not_b2b'] = tsg['is_b2b'] == 0
    if 'days_rest' in tsg.columns:
        conditions['rest_3+'] = tsg['days_rest'] >= 3
        conditions['rest_5+'] = tsg['days_rest'] >= 5

    # Home/away
    if 'is_home' in tsg.columns:
        conditions['is_home'] = tsg['is_home'] == 1
        conditions['is_away'] = tsg['is_home'] == 0

    # Day of week
    if 'dow' in tsg.columns:
        conditions['weekend'] = tsg['dow'].isin([5, 6])
        conditions['weekday'] = ~tsg['dow'].isin([5, 6])

    # Month
    if 'month' in tsg.columns:
        conditions['early_season'] = tsg['month'].isin([10, 11])
        conditions['mid_season'] = tsg['month'].isin([12, 1, 2])
        conditions['late_season'] = tsg['month'].isin([3, 4])

    # Rolling stat conditions
    for col in ['shots_on_goal_avg_5','shots_on_goal_avg_10','hits_avg_5','hits_avg_10']:
        if col in tsg.columns:
            tsg[col].median()
            conditions[f'{col}_high'] = tsg[col] > tsg[col].quantile(0.75)
            conditions[f'{col}_low'] = tsg[col] < tsg[col].quantile(0.25)

    for col in ['opp_shots_on_goal_avg_5','opp_shots_on_goal_avg_10','opp_hits_avg_5']:
        if col in tsg.columns:
            conditions[f'{col}_high'] = tsg[col] > tsg[col].quantile(0.75)

    # Win streak
    if 'win_streak' in tsg.columns:
        conditions['hot_team_7+'] = tsg['win_streak'] >= 7
        conditions['cold_team_3-'] = tsg['win_streak'] <= 3

    # Fwd absences
    if 'opp_fwd_missing' in tsg.columns:
        conditions['opp_2+F_missing'] = tsg['opp_fwd_missing'] >= 2
    if 'fwd_missing' in tsg.columns:
        conditions['own_3+F_missing'] = tsg['fwd_missing'] >= 3

    # PP opportunities rolling
    if 'power_play_opportunities_avg_5' in tsg.columns:
        conditions['high_pp_opps'] = tsg['power_play_opportunities_avg_5'] > tsg['power_play_opportunities_avg_5'].quantile(0.75)
    if 'opp_power_play_opportunities_avg_5' in tsg.columns:
        conditions['opp_high_pp_opps'] = tsg['opp_power_play_opportunities_avg_5'] > tsg['opp_power_play_opportunities_avg_5'].quantile(0.75)

    # Absence rolling (persistence signal)
    if 'opp_def_missing_avg_5' in tsg.columns:
        conditions['opp_D_missing_persistent'] = tsg['opp_def_missing_avg_5'] >= 2.5
    if 'def_missing_avg_5' in tsg.columns:
        conditions['own_D_missing_persistent'] = tsg['def_missing_avg_5'] >= 2.5

    return conditions

def evaluate_strategy(target_vals, condition_mask, season_vals, min_bets_per_season=20, min_seasons=3):
    """Evaluate a single strategy across seasons. Returns None if not viable."""
    results = []
    seasons = sorted(season_vals.unique())

    for s in seasons:
        s_mask = season_vals == s
        active = condition_mask & s_mask

        if active.sum() < min_bets_per_season:
            continue

        wins = target_vals[active].sum()
        n = active.sum()
        losses = n - wins
        profit = wins * 100 - losses * 110  # -110 odds
        roi = profit / (n * 110) * 100
        win_pct = wins / n * 100

        results.append({
            'season': int(s),
            'roi': round(roi, 2),
            'win_pct': round(win_pct, 2),
            'bets': int(n),
            'wins': int(wins)
        })

    if len(results) < min_seasons:
        return None

    # Check: positive ROI in ALL seasons?
    all_positive = all(r['roi'] > 0 for r in results)
    # Or: positive in 3+ seasons with avg ROI > 3%
    avg_roi = np.mean([r['roi'] for r in results])
    total_bets = sum(r['bets'] for r in results)
    positive_seasons = sum(1 for r in results if r['roi'] > 0)

    if avg_roi < 2.0 or positive_seasons < len(results) - 1:
        return None

    # Combined stats
    total_wins = sum(r['wins'] for r in results)
    total_profit = total_wins * 100 - (total_bets - total_wins) * 110
    combined_roi = total_profit / (total_bets * 110) * 100
    combined_win_pct = total_wins / total_bets * 100

    return {
        'seasons': results,
        'combined_roi': round(combined_roi, 2),
        'combined_win_pct': round(combined_win_pct, 2),
        'total_bets': total_bets,
        'positive_seasons': positive_seasons,
        'total_seasons': len(results),
        'all_positive': all_positive,
        'avg_roi': round(avg_roi, 2)
    }

def run_search(tsg, targets, conditions, run_id=0, max_combo_size=3):
    """Run one iteration of the brute-force search."""
    print(f"\n{'='*60}")
    print(f"  RUN {run_id}: Testing {len(targets)} targets × {len(conditions)} conditions")
    print(f"  + combos up to size {max_combo_size}")
    print(f"{'='*60}")

    season_vals = tsg['season']
    findings = []
    tested = 0

    # Single conditions
    for tname, tvals in targets.items():
        if tvals is None:
            continue
        for cname, cmask in conditions.items():
            result = evaluate_strategy(tvals, cmask, season_vals)
            tested += 1
            if result:
                result['target'] = tname
                result['conditions'] = [cname]
                result['run_id'] = run_id
                findings.append(result)

    print(f"  Singles tested: {tested}, found: {len(findings)}")

    # Two-condition combos
    cond_names = list(conditions.keys())
    np.random.seed(run_id * 42)

    # Sample pairs (too many to test all)
    n_pairs = min(2000, len(cond_names) * (len(cond_names) - 1) // 2)
    pairs_tested = 0

    for _ in range(n_pairs):
        i, j = np.random.choice(len(cond_names), 2, replace=False)
        c1, c2 = cond_names[i], cond_names[j]
        combo_mask = conditions[c1] & conditions[c2]

        if combo_mask.sum() < 80:  # need enough bets
            continue

        for tname, tvals in targets.items():
            if tvals is None:
                continue
            result = evaluate_strategy(tvals, combo_mask, season_vals)
            pairs_tested += 1
            if result:
                result['target'] = tname
                result['conditions'] = sorted([c1, c2])
                result['run_id'] = run_id
                findings.append(result)

    print(f"  Pairs tested: {pairs_tested}, total found: {len(findings)}")

    # Three-condition combos (sampled)
    if max_combo_size >= 3:
        triples_tested = 0
        for _ in range(1000):
            idx = np.random.choice(len(cond_names), 3, replace=False)
            c1, c2, c3 = cond_names[idx[0]], cond_names[idx[1]], cond_names[idx[2]]
            combo_mask = conditions[c1] & conditions[c2] & conditions[c3]

            if combo_mask.sum() < 50:
                continue

            for tname, tvals in targets.items():
                if tvals is None:
                    continue
                result = evaluate_strategy(tvals, combo_mask, season_vals)
                triples_tested += 1
                if result:
                    result['target'] = tname
                    result['conditions'] = sorted([c1, c2, c3])
                    result['run_id'] = run_id
                    findings.append(result)

        print(f"  Triples tested: {triples_tested}, total found: {len(findings)}")

    return findings

def deduplicate_findings(all_findings):
    """Remove duplicate strategies, keep best version."""
    seen = {}
    for f in all_findings:
        key = f"{f['target']}|{'&'.join(f['conditions'])}"
        if key not in seen or f['combined_roi'] > seen[key]['combined_roi']:
            seen[key] = f
    return list(seen.values())

def main():
    start = datetime.now()
    games, ts, ab, gs, ps, stand, odds = load_all_data()
    tsg = build_game_features(games, ts, ab, gs, ps, stand)
    targets = define_targets(tsg)
    conditions = define_conditions(tsg)

    print(f"\nTargets: {len(targets)}")
    for t in targets:
        print(f"  {t}")
    print(f"\nConditions: {len(conditions)}")

    all_findings = []

    # Run 20 iterations with different random seeds and combo sampling
    for run_id in range(20):
        findings = run_search(tsg, targets, conditions, run_id=run_id)
        all_findings.extend(findings)
        print(f"  Run {run_id}: {len(findings)} strategies found ({len(all_findings)} total)")

    # Deduplicate
    unique = deduplicate_findings(all_findings)

    # Sort by combined ROI
    unique.sort(key=lambda x: x['combined_roi'], reverse=True)

    # Save all results
    with open(RESULTS_FILE, 'w') as f:
        json.dump({
            'timestamp': str(datetime.now()),
            'runtime_seconds': (datetime.now() - start).total_seconds(),
            'total_strategies_found': len(unique),
            'strategies': unique[:200]  # top 200
        }, f, indent=2)

    # Print top findings
    print(f"\n{'='*70}")
    print(f"  DR. STRANGE RESULTS: {len(unique)} viable strategies found")
    print(f"  Runtime: {(datetime.now() - start).total_seconds():.0f}s")
    print(f"{'='*70}")

    # Top 30 by combined ROI
    print(f"\n{'Rank':<5} {'Target':<30} {'Conditions':<45} {'ROI':>7} {'Win%':>7} {'Bets':>6} {'Szns':>5} {'All+':>5}")
    print("-" * 110)

    for i, s in enumerate(unique[:30], 1):
        conds = ' & '.join(s['conditions'])
        allp = '✅' if s['all_positive'] else '❌'
        print(f"{i:<5} {s['target']:<30} {conds:<45} {s['combined_roi']:>6.1f}% {s['combined_win_pct']:>6.1f}% {s['total_bets']:>5} {s['positive_seasons']}/{s['total_seasons']}  {allp}")

    # Highlight ALL-POSITIVE-SEASON strategies
    all_pos = [s for s in unique if s['all_positive'] and s['total_bets'] >= 100]
    print(f"\n{'='*70}")
    print(f"  ⭐ STRATEGIES WITH ALL SEASONS POSITIVE (N>=100): {len(all_pos)}")
    print(f"{'='*70}")

    for i, s in enumerate(all_pos[:20], 1):
        conds = ' & '.join(s['conditions'])
        print(f"\n  #{i}: {s['target']} | {conds}")
        print(f"      ROI={s['combined_roi']:.1f}%, Win={s['combined_win_pct']:.1f}%, Bets={s['total_bets']}")
        for ss in s['seasons']:
            print(f"        {ss['season']}: ROI={ss['roi']:+.1f}%, Win={ss['win_pct']:.1f}%, N={ss['bets']}")

if __name__ == '__main__':
    main()
