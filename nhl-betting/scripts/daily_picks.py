"""
NHC Daily Picks Pipeline
Pulls live odds, runs V2 model + hit rate filter, outputs picks with confidence.
"""
import subprocess
import time
from collections import defaultdict
from io import StringIO

import pandas as pd
import requests

API_KEY = '53b74c4c440a14071dac325d834a55b8'
PSQL = '/opt/homebrew/Cellar/postgresql@17/17.8/bin/psql'
DB = 'nhl_betting'

def query(sql):
    r = subprocess.run([PSQL, '-d', DB, '-c', f"COPY ({sql}) TO STDOUT WITH CSV HEADER"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return pd.DataFrame()
    return pd.read_csv(StringIO(r.stdout))

# ===================================
# 1. PULL LIVE ODDS
# ===================================
print("=" * 70)
print("PULLING LIVE ODDS")
print("=" * 70)

# Get tonight's events
events_r = requests.get(f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events?apiKey={API_KEY}")
events = events_r.json()
tonight = [e for e in events if '2026-02-27' in e['commence_time'] or '2026-02-26T2' in e['commence_time']]
print(f"Tonight: {len(tonight)} games")

# Pull player_points OVER 1.5 and OVER 0.5 for all games
all_props = []
for ev in tonight:
    eid = ev['id']
    game = f"{ev['away_team']} @ {ev['home_team']}"
    url = f"https://api.the-odds-api.com/v4/sports/icehockey_nhl/events/{eid}/odds?apiKey={API_KEY}&regions=us,us2&markets=player_points,player_assists,player_shots_on_goal&oddsFormat=american&bookmakers=draftkings,fanduel,betmgm,hardrockbet"
    r = requests.get(url)
    d = r.json()
    for bk in d.get('bookmakers', []):
        for mkt in bk.get('markets', []):
            for o in mkt.get('outcomes', []):
                all_props.append({
                    'game': game, 'book': bk['key'], 'market': mkt['key'],
                    'player': o.get('description', ''), 'side': o['name'],
                    'line': o.get('point', 0), 'odds': o['price'],
                })
    time.sleep(0.3)

print(f"Total prop lines: {len(all_props)}")

# ===================================
# 2. GET PLAYER SEASON STATS (NHL API)
# ===================================
print("\n" + "=" * 70)
print("PULLING PLAYER SEASON STATS")
print("=" * 70)

# Get unique players from props
unique_players = set(p['player'] for p in all_props if p['player'])
print(f"Unique players in tonight's props: {len(unique_players)}")

# Search NHL API for each player's stats
player_stats = {}
player_ids_checked = set()

def get_player_stats(name):
    """Get player's season stats from NHL API."""
    last_name = name.split()[-1]
    search_r = requests.get(f"https://search.d3.nhle.com/api/v1/search/player?culture=en-us&limit=5&q={last_name}")
    results = search_r.json()

    for p in results:
        if p['name'] == name and p.get('active'):
            pid = p['playerId']
            if pid in player_ids_checked:
                return player_stats.get(pid)
            player_ids_checked.add(pid)

            stats_r = requests.get(f"https://api-web.nhle.com/v1/player/{pid}/game-log/20252026/2")
            games = stats_r.json().get('gameLog', [])
            if not games:
                return None

            gp = len(games)
            total_pts = sum(g.get('goals',0) + g.get('assists',0) for g in games)
            total_assists = sum(g.get('assists',0) for g in games)
            games_2plus = sum(1 for g in games if (g.get('goals',0) + g.get('assists',0)) >= 2)
            games_1plus = sum(1 for g in games if (g.get('goals',0) + g.get('assists',0)) >= 1)

            stats = {
                'player_id': pid, 'name': name, 'gp': gp,
                'pts': total_pts, 'ppg': round(total_pts/gp, 3),
                'assists': total_assists, 'apg': round(total_assists/gp, 3),
                'mp_rate': round(games_2plus/gp, 3),  # 2+ points hit rate
                'point_rate': round(games_1plus/gp, 3),  # 1+ points hit rate
                'mp_games': games_2plus, 'point_games': games_1plus,
            }
            player_stats[pid] = stats
            return stats
    return None

# Batch lookup — focus on players with 1.5 lines
players_15 = set(
    p['player'] for p in all_props
    if p['line'] == 1.5 and p['side'] == 'Over' and p['market'] == 'player_points'
)
players_05 = set(
    p['player'] for p in all_props
    if p['line'] == 0.5 and p['side'] == 'Over' and p['market'] == 'player_points'
)
all_needed = players_15 | players_05

print(f"Looking up {len(all_needed)} players...")
for i, name in enumerate(all_needed):
    get_player_stats(name)
    if i % 20 == 0 and i > 0:
        print(f"  ...{i}/{len(all_needed)}")
        time.sleep(0.5)

print(f"Found stats for {len(player_stats)} players")

# ===================================
# 3. GENERATE PICKS
# ===================================
print("\n" + "=" * 70)
print("GENERATING PICKS")
print("=" * 70)

# Best odds per player/market/side/line
best_odds = defaultdict(lambda: None)
for p in all_props:
    key = (p['player'], p['market'], p['side'], p['line'])
    if best_odds[key] is None or p['odds'] > best_odds[key]['odds']:
        best_odds[key] = p

# === STRATEGY C: OVER 1.5 POINTS (V2 model-informed) ===
print("\n--- STRATEGY C: OVER 1.5 POINTS ---")
c_picks = []
for (player, market, side, line), prop in best_odds.items():
    if market != 'player_points' or side != 'Over' or line != 1.5:
        continue

    stats = None
    for s in player_stats.values():
        if s['name'] == player:
            stats = s
            break
    if not stats or stats['gp'] < 10:
        continue

    mp_rate = stats['mp_rate']
    odds = prop['odds']

    # Breakeven calculation
    if odds > 0:
        breakeven = 100 / (odds + 100)
    else:
        breakeven = abs(odds) / (abs(odds) + 100)

    edge = mp_rate - breakeven

    # Deploy rules: hit rate >= 30% AND positive edge
    if mp_rate >= 0.30 and edge > 0:
        # Confidence scoring
        if mp_rate >= 0.40 and edge >= 0.10:
            confidence = "🟢 HIGH"
        elif mp_rate >= 0.35 and edge >= 0.05:
            confidence = "🟢 HIGH"
        elif mp_rate >= 0.30 and edge >= 0.03:
            confidence = "🟡 MEDIUM"
        else:
            confidence = "🟡 MEDIUM"

        c_picks.append({
            **prop,
            'mp_rate': mp_rate, 'mp_games': stats['mp_games'], 'gp': stats['gp'],
            'breakeven': breakeven, 'edge': edge, 'confidence': confidence,
            'ppg': stats['ppg'],
        })

# Team concentration cap: max 1 per team for OVER 1.5 (unless edge >= 15%)
c_picks.sort(key=lambda x: -x['edge'])
MASSIVE_EDGE = 0.15


def get_player_team(name, game_str):
    """Look up player's current team from DB, fallback to game string."""
    result = query(
        f"SELECT t.tri_code FROM players p JOIN teams t "
        f"ON p.current_team_id = t.team_id "
        f"WHERE p.first_name || ' ' || p.last_name = '{name.replace(chr(39), chr(39)*2)}' "
        f"LIMIT 1"
    )
    if not result.empty:
        return result.iloc[0]['tri_code']
    return game_str  # fallback


c_filtered = []
team_count_c = defaultdict(int)
for p in c_picks:
    team_key = get_player_team(p['player'], p['game'])
    if team_count_c[team_key] >= 1 and p['edge'] < MASSIVE_EDGE:
        continue
    c_filtered.append(p)
    team_count_c[team_key] += 1
c_picks = c_filtered
print(f"C picks (OVER 1.5 pts, max 1/team): {len(c_picks)}")
for p in c_picks:
    odds_str = f"+{p['odds']}" if p['odds'] > 0 else str(p['odds'])
    print(f"  {p['confidence']} | {p['player']} | {p['game']} | {odds_str} @ {p['book']} | "
          f"Hit: {p['mp_rate']*100:.1f}% ({p['mp_games']}/{p['gp']}) | "
          f"BE: {p['breakeven']*100:.1f}% | Edge: {p['edge']*100:+.1f}%")

# === STRATEGY B2: OVER 0.5 POINTS (minus odds value) ===
print("\n--- STRATEGY B2: OVER 0.5 POINTS (singles) ---")
b2_picks = []
for (player, market, side, line), prop in best_odds.items():
    if market != 'player_points' or side != 'Over' or line != 0.5:
        continue

    stats = None
    for s in player_stats.values():
        if s['name'] == player:
            stats = s
            break
    if not stats or stats['gp'] < 10:
        continue

    point_rate = stats['point_rate']
    odds = prop['odds']

    if odds > 0:
        breakeven = 100 / (odds + 100)
    else:
        breakeven = abs(odds) / (abs(odds) + 100)

    edge = point_rate - breakeven

    # Deploy: edge > 3% AND (minus odds for singles OR plus money > +150)
    if edge >= 0.03 and point_rate >= 0.55:
        if odds >= 150:
            confidence = "🟢 HIGH" if edge >= 0.10 else "🟡 MEDIUM"
        elif -200 <= odds < 0:
            confidence = "🟢 HIGH" if edge >= 0.06 else "🟡 MEDIUM"
        elif odds < -200:
            confidence = "🟡 MEDIUM" if edge >= 0.05 else "⚪ LOW"
        else:
            confidence = "🟡 MEDIUM"

        b2_picks.append({
            **prop,
            'point_rate': point_rate, 'point_games': stats['point_games'], 'gp': stats['gp'],
            'breakeven': breakeven, 'edge': edge, 'confidence': confidence,
            'ppg': stats['ppg'],
        })

# Team concentration cap: max 2 per team for OVER 0.5 (unless edge >= 15%)
b2_picks.sort(key=lambda x: -x['edge'])
b2_filtered = []
team_count_b2 = defaultdict(int)
for p in b2_picks:
    team_key = get_player_team(p['player'], p['game'])
    if team_count_b2[team_key] >= 2 and p['edge'] < MASSIVE_EDGE:
        continue
    b2_filtered.append(p)
    team_count_b2[team_key] += 1
b2_picks = b2_filtered
print(f"B2 picks (OVER 0.5 pts, max 2/team): {len(b2_picks)}")
for p in b2_picks[:20]:  # Top 20
    odds_str = f"+{p['odds']}" if p['odds'] > 0 else str(p['odds'])
    print(f"  {p['confidence']} | {p['player']} | {p['game']} | {odds_str} @ {p['book']} | "
          f"Hit: {p['point_rate']*100:.1f}% ({p['point_games']}/{p['gp']}) | "
          f"BE: {p['breakeven']*100:.1f}% | Edge: {p['edge']*100:+.1f}%")

# === STRATEGY B1: ASSISTS UNDER 0.5 (plus money, low-assist players) ===
print("\n--- STRATEGY B1: ASSISTS UNDER 0.5 ---")
b1_picks = []
for (player, market, side, line), prop in best_odds.items():
    if market != 'player_assists' or side != 'Under' or line != 0.5:
        continue
    if prop['odds'] < 110:  # Must be plus money
        continue

    stats = None
    for s in player_stats.values():
        if s['name'] == player:
            stats = s
            break
    if not stats or stats['gp'] < 10:
        continue

    # UNDER 0.5 assists hit rate = 1 - (games with 1+ assist / gp)
    # We need to screen OUT high-assist players
    if stats['apg'] >= 0.50:  # Skip anyone averaging 0.5+ assists/game
        continue

    under_rate = 1 - stats['apg']  # Rough proxy
    odds = prop['odds']
    breakeven = 100 / (odds + 100)
    edge = under_rate - breakeven

    if edge >= 0.03:
        confidence = "🟢 HIGH" if edge >= 0.10 else "🟡 MEDIUM"
        b1_picks.append({
            **prop,
            'under_rate': under_rate, 'apg': stats['apg'], 'gp': stats['gp'],
            'breakeven': breakeven, 'edge': edge, 'confidence': confidence,
        })

b1_picks.sort(key=lambda x: -x['edge'])
print(f"B1 picks (Assists UNDER): {len(b1_picks)}")
for p in b1_picks[:10]:
    odds_str = f"+{p['odds']}" if p['odds'] > 0 else str(p['odds'])
    print(f"  {p['confidence']} | {p['player']} | {p['game']} | {odds_str} @ {p['book']} | "
          f"A/GP: {p['apg']:.2f} | UNDER rate: {p['under_rate']*100:.1f}% | Edge: {p['edge']*100:+.1f}%")

# === SUMMARY ===
print("\n" + "=" * 70)
print("TONIGHT'S FINAL PICKS")
print("=" * 70)

all_picks = []
for p in c_picks:
    all_picks.append({
        'strategy': 'C: OVER 1.5 pts',
        'player': p['player'], 'game': p['game'],
        'odds': p['odds'], 'book': p['book'],
        'confidence': p['confidence'],
        'hit_rate': p['mp_rate'], 'edge': p['edge'],
        'reasoning': f"{p['mp_games']}/{p['gp']} multi-pt games ({p['mp_rate']*100:.1f}%),"
                f" {p['ppg']:.2f} P/GP, BE={p['breakeven']*100:.1f}%"
    })

for p in b2_picks[:15]:  # Top 15 singles
    all_picks.append({
        'strategy': 'B2: OVER 0.5 pts',
        'player': p['player'], 'game': p['game'],
        'odds': p['odds'], 'book': p['book'],
        'confidence': p['confidence'],
        'hit_rate': p['point_rate'], 'edge': p['edge'],
        'reasoning': f"{p['point_games']}/{p['gp']} point games ({p['point_rate']*100:.1f}%),"
                f" {p['ppg']:.2f} P/GP, BE={p['breakeven']*100:.1f}%"
    })

for p in b1_picks[:5]:
    all_picks.append({
        'strategy': 'B1: Assists UNDER',
        'player': p['player'], 'game': p['game'],
        'odds': p['odds'], 'book': p['book'],
        'confidence': p['confidence'],
        'hit_rate': p['under_rate'], 'edge': p['edge'],
        'reasoning': f"{p['apg']:.2f} A/GP, UNDER hits ~{p['under_rate']*100:.0f}%, BE={p['breakeven']*100:.1f}%"
    })

print(f"\nTotal picks: {len(all_picks)}")
print(f"  Strategy C (OVER 1.5): {len(c_picks)}")
print(f"  Strategy B2 (OVER 0.5): {min(len(b2_picks), 15)}")
print(f"  Strategy B1 (Assists UNDER): {min(len(b1_picks), 5)}")

for p in all_picks:
    odds_str = f"+{p['odds']}" if p['odds'] > 0 else str(p['odds'])
    print(f"\n{p['confidence']} | {p['strategy']} | {p['player']} | {p['game']}")
    print(f"  {odds_str} @ {p['book']} | Edge: {p['edge']*100:+.1f}%")
    print(f"  {p['reasoning']}")

# Check API quota
r = requests.get(f"https://api.the-odds-api.com/v4/sports/?apiKey={API_KEY}")
print(f"\nAPI requests remaining: {r.headers.get('x-requests-remaining')}")
