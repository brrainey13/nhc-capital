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
    psql_copy("SELECT game_id, game_date, season, home_team_id, away_team_id FROM games WHERE game_type IN (2, 3) AND game_state = 'OFF'", '/tmp/ds_games.csv')
    games = pd.read_csv('/tmp/ds_games.csv')
    games['game_date'] = pd.to_datetime(games['game_date'])
    games['dow'] = games['game_date'].dt.dayofweek
    games['month'] = games['game_date'].dt.month
    games['game_num'] = games.groupby(['home_team_id','season']).cumcount() + 1

    # Team stats (both teams per game) — filtered to analysis games only
    psql_copy("""SELECT gts.game_id, gts.team_id, gts.is_home, gts.score, gts.shots_on_goal, gts.shots_attempted,
                 gts.power_play_goals, gts.power_play_opportunities, gts.pim, gts.hits, gts.blocked_shots,
                 gts.faceoff_win_pct, gts.giveaways, gts.takeaways, gts.won
                 FROM game_team_stats gts
                 JOIN games g ON gts.game_id = g.game_id
                 WHERE g.game_type IN (2, 3) AND g.game_state = 'OFF'""", '/tmp/ds_ts.csv')
    ts = pd.read_csv('/tmp/ds_ts.csv')

    # Absences (filtered to analysis games)
    psql_copy("""SELECT la.game_id, la.team_id, la.def_missing, la.def_missing_toi, la.fwd_missing,
                 la.fwd_missing_toi, la.total_missing, la.total_missing_toi
                 FROM lineup_absences la
                 JOIN games g ON la.game_id = g.game_id
                 WHERE g.game_type IN (2, 3) AND g.game_state = 'OFF'""", '/tmp/ds_abs.csv')
    ab = pd.read_csv('/tmp/ds_abs.csv')

    # Goalie stats (filtered)
    psql_copy("""SELECT gs.game_id, gs.player_id, gs.team_id, gs.saves, gs.shots_against,
                 gs.goals_against, gs.save_pct, gs.toi_minutes, gs.started,
                 p.first_name || ' ' || p.last_name as goalie_name
                 FROM goalie_stats gs
                 JOIN players p ON gs.player_id = p.player_id
                 JOIN games g ON gs.game_id = g.game_id
                 WHERE gs.shots_against > 0 AND g.game_type IN (2, 3) AND g.game_state = 'OFF'""", '/tmp/ds_gs.csv')
    gs = pd.read_csv('/tmp/ds_gs.csv')

    # Period scores (filtered)
    psql_copy("""SELECT ps.game_id, ps.team_id, ps.period_number as period, ps.goals
                 FROM period_scores ps
                 JOIN games g ON ps.game_id = g.game_id
                 WHERE ps.period_number <= 3 AND g.game_type IN (2, 3) AND g.game_state = 'OFF'""", '/tmp/ds_ps.csv')
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
    """Define bettable outcomes using DYNAMIC per-season median lines.

    Books set lines near the median (50/50 split), so that's where real edges live.
    We test at median, median+1, and median-1 to bracket realistic book lines.
    We also compute blind over rates per target to flag fake edges.
    """
    targets = {}
    blind_rates = {}  # Track blind over rate to validate edges later

    # Compute per-season medians for each stat
    stat_medians = {}
    for col in ['shots_on_goal', 'hits', 'blocked_shots', 'pim', 'score', 'shots_attempted',
                'giveaways', 'takeaways']:
        if col in tsg.columns:
            stat_medians[col] = tsg.groupby('season')[col].transform('median')

    # Helper: add target at a dynamic line
    def add_dynamic_target(name, col, offset=0):
        if col not in stat_medians:
            return
        line = stat_medians[col] + offset
        over = (tsg[col] > line).astype(int)
        targets[name] = over
        blind_rates[name] = over.mean()

    # Team SOG — the main thesis. Test at median, +1, +2, -1
    for off in [-1, 0, 1, 2]:
        label = f"team_sog_over_median{off:+d}" if off != 0 else "team_sog_over_median"
        add_dynamic_target(label, 'shots_on_goal', off)

    # Team hits — test at realistic lines around median
    for off in [-1, 0, 1, 2]:
        label = f"team_hits_over_median{off:+d}" if off != 0 else "team_hits_over_median"
        add_dynamic_target(label, 'hits', off)

    # Team blocks
    for off in [-1, 0, 1]:
        label = f"team_blocks_over_median{off:+d}" if off != 0 else "team_blocks_over_median"
        add_dynamic_target(label, 'blocked_shots', off)

    # PIM
    for off in [-1, 0, 1]:
        label = f"team_pim_over_median{off:+d}" if off != 0 else "team_pim_over_median"
        add_dynamic_target(label, 'pim', off)

    # Shots attempted
    for off in [-2, 0, 2]:
        label = f"team_sa_over_median{off:+d}" if off != 0 else "team_sa_over_median"
        add_dynamic_target(label, 'shots_attempted', off)

    # Giveaways / takeaways (niche props some books offer)
    for off in [0, 1]:
        label = f"team_giveaways_over_median{off:+d}" if off != 0 else "team_giveaways_over_median"
        add_dynamic_target(label, 'giveaways', off)
        label = f"team_takeaways_over_median{off:+d}" if off != 0 else "team_takeaways_over_median"
        add_dynamic_target(label, 'takeaways', off)

    # Team goals (standard book lines)
    targets['team_goals_over_2.5'] = (tsg['score'] > 2.5).astype(int)
    targets['team_goals_over_3.5'] = (tsg['score'] > 3.5).astype(int)
    blind_rates['team_goals_over_2.5'] = targets['team_goals_over_2.5'].mean()
    blind_rates['team_goals_over_3.5'] = targets['team_goals_over_3.5'].mean()

    # Total game goals (standard book lines)
    if 'opp_score' in tsg.columns:
        total_goals = tsg['score'] + tsg['opp_score']
        for line in [5.5, 6.5]:
            name = f'total_goals_over_{line}'
            targets[name] = (total_goals > line).astype(int)
            blind_rates[name] = targets[name].mean()

    # Period goals
    if 'p1_goals' in tsg.columns:
        targets['p1_goals_over_0.5'] = (tsg['p1_goals'] > 0.5).astype(int)
        targets['p1_goals_over_1.5'] = (tsg['p1_goals'] > 1.5).astype(int)
        blind_rates['p1_goals_over_0.5'] = targets['p1_goals_over_0.5'].mean()
        blind_rates['p1_goals_over_1.5'] = targets['p1_goals_over_1.5'].mean()
        if 'opp_p1_goals' in tsg.columns:
            total_p1 = tsg['p1_goals'] + tsg['opp_p1_goals']
            targets['total_p1_goals_over_1.5'] = (total_p1 > 1.5).astype(int)
            blind_rates['total_p1_goals_over_1.5'] = targets['total_p1_goals_over_1.5'].mean()

    # Team wins (moneyline)
    targets['team_win'] = tsg['won'].astype(int)
    blind_rates['team_win'] = targets['team_win'].mean()

    # PP goals over 0.5 (common prop)
    if 'power_play_goals' in tsg.columns:
        targets['team_ppg_over_0.5'] = (tsg['power_play_goals'] > 0.5).astype(int)
        blind_rates['team_ppg_over_0.5'] = targets['team_ppg_over_0.5'].mean()

    # Remove None targets
    targets = {k: v for k, v in targets.items() if v is not None}

    # Print blind rates as sanity check
    print("\n  BLIND OVER RATES (no conditions — if >52.4%, blind bet already profitable at -110):")
    for name, rate in sorted(blind_rates.items(), key=lambda x: -x[1]):
        flag = " ⚠️  BLIND BET ALREADY WINS" if rate > 0.524 else ""
        print(f"    {name}: {rate:.1%}{flag}")

    return targets, blind_rates

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

def evaluate_strategy(target_vals, condition_mask, season_vals, blind_rate=None,
                      min_bets_per_season=20, min_seasons=3):
    """Evaluate a single strategy across seasons. Returns None if not viable.

    Key validation: the conditional win% must EXCEED the blind over rate.
    If the blind rate is already >52.4%, the target is suspect at that line.
    """
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

        # Season-specific blind rate for comparison
        s_blind = target_vals[s_mask].mean() * 100

        results.append({
            'season': int(s),
            'roi': round(roi, 2),
            'win_pct': round(win_pct, 2),
            'bets': int(n),
            'wins': int(wins),
            'blind_rate': round(s_blind, 2)
        })

    if len(results) < min_seasons:
        return None

    # Check: positive ROI in ALL seasons?
    all_positive = all(r['roi'] > 0 for r in results)
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

    # CRITICAL: Compute edge over blind rate
    overall_blind = blind_rate * 100 if blind_rate else target_vals.mean() * 100
    edge_over_blind = combined_win_pct - overall_blind

    # Reject if the conditional win% doesn't meaningfully beat blind rate
    # (i.e., the condition isn't actually adding value)
    if edge_over_blind < 2.0:
        return None

    return {
        'seasons': results,
        'combined_roi': round(combined_roi, 2),
        'combined_win_pct': round(combined_win_pct, 2),
        'total_bets': total_bets,
        'positive_seasons': positive_seasons,
        'total_seasons': len(results),
        'all_positive': all_positive,
        'avg_roi': round(avg_roi, 2),
        'blind_over_rate': round(overall_blind, 2),
        'edge_over_blind': round(edge_over_blind, 2)
    }

def run_search(tsg, targets, conditions, blind_rates, run_id=0, max_combo_size=3):
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
        br = blind_rates.get(tname)
        for cname, cmask in conditions.items():
            result = evaluate_strategy(tvals, cmask, season_vals, blind_rate=br)
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

    n_pairs = min(2000, len(cond_names) * (len(cond_names) - 1) // 2)
    pairs_tested = 0

    for _ in range(n_pairs):
        i, j = np.random.choice(len(cond_names), 2, replace=False)
        c1, c2 = cond_names[i], cond_names[j]
        combo_mask = conditions[c1] & conditions[c2]

        if combo_mask.sum() < 80:
            continue

        for tname, tvals in targets.items():
            if tvals is None:
                continue
            br = blind_rates.get(tname)
            result = evaluate_strategy(tvals, combo_mask, season_vals, blind_rate=br)
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
                br = blind_rates.get(tname)
                result = evaluate_strategy(tvals, combo_mask, season_vals, blind_rate=br)
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
    targets, blind_rates = define_targets(tsg)
    conditions = define_conditions(tsg)

    print(f"\nTargets: {len(targets)}")
    for t in targets:
        print(f"  {t}")
    print(f"\nConditions: {len(conditions)}")

    all_findings = []

    # Number of iterations (default 3, override via env)
    n_runs = int(os.environ.get('DS_RUNS', 3))
    # Seed offset to avoid repeating prior runs
    seed_offset = int(os.environ.get('DS_SEED_OFFSET', 20))

    for run_id in range(seed_offset, seed_offset + n_runs):
        findings = run_search(tsg, targets, conditions, blind_rates, run_id=run_id)
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
    print(f"\n{'Rank':<5} {'Target':<30} {'Conditions':<40} {'ROI':>7} {'Win%':>7} {'Blind':>7} {'Edge':>7} {'Bets':>6} {'Szns':>5}")
    print("-" * 120)

    for i, s in enumerate(unique[:30], 1):
        conds = ' & '.join(s['conditions'])
        print(f"{i:<5} {s['target']:<30} {conds:<40} {s['combined_roi']:>6.1f}% {s['combined_win_pct']:>6.1f}% {s.get('blind_over_rate',0):>6.1f}% {s.get('edge_over_blind',0):>+6.1f}% {s['total_bets']:>5} {s['positive_seasons']}/{s['total_seasons']}")

    # Highlight ALL-POSITIVE-SEASON strategies
    all_pos = [s for s in unique if s['all_positive'] and s['total_bets'] >= 100]
    print(f"\n{'='*70}")
    print(f"  ⭐ STRATEGIES WITH ALL SEASONS POSITIVE (N>=100): {len(all_pos)}")
    print(f"{'='*70}")

    for i, s in enumerate(all_pos[:20], 1):
        conds = ' & '.join(s['conditions'])
        print(f"\n  #{i}: {s['target']} | {conds}")
        print(f"      ROI={s['combined_roi']:.1f}%, Win={s['combined_win_pct']:.1f}%, Blind={s.get('blind_over_rate',0):.1f}%, Edge={s.get('edge_over_blind',0):+.1f}pp, Bets={s['total_bets']}")
        for ss in s['seasons']:
            blind = ss.get('blind_rate', 0)
            print(f"        {ss['season']}: ROI={ss['roi']:+.1f}%, Win={ss['win_pct']:.1f}%, Blind={blind:.1f}%, N={ss['bets']}")

if __name__ == '__main__':
    main()
