#!/usr/bin/env python3
"""Hockey Goalie Scanner v3 - Simpler parsing."""

import os
import re
from datetime import datetime

import requests

DB_CONFIG = {
    "host": "localhost",
    "database": "clawd",
    "user": "clawd_user",
    "password": os.environ.get("CLAWD_DB_PASSWORD", "")
}

QUANTHOCKEY_URL = "https://www.quanthockey.com/nhl/seasons/nhl-goalies-stats.html"

def fetch_quanthockey():
    """Fetch raw HTML from QuantHockey"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
        r = requests.get(QUANTHOCKEY_URL, headers=headers, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        print(f"Error fetching QuantHockey: {e}")
        return None

def parse_goalie_stats(html):
    """
    Parse goalie stats from QuantHockey HTML
    Simpler approach: find name, grab next team code, then numbers
    """
    goalies = []

    if not html:
        return goalies

    # Find all hockey-stats profile links
    # These are the goalie names in rows
    name_pattern = r'href="/hockey-stats/en/profile\.php[^>]*>([^<]+)</a>'
    names = re.finditer(name_pattern, html)

    for match in names:
        name = match.group(1).strip()
        start_pos = match.end()

        # Look ahead from this position for team code
        # Pattern: find 3 uppercase letters in </a></td> after this name
        ahead = html[start_pos:start_pos+500]

        team_match = re.search(r'>([A-Z]{3})</a></td>', ahead)
        if not team_match:
            continue
        team = team_match.group(1)

        # Now find the numeric data
        # Look for: <td>AGE</td>...<td>GP</td>...<td>GAA</td>...<td>SV%</td>
        numbers_ahead = html[start_pos:start_pos+1000]
        numbers = re.findall(r'<td[^>]*>([0-9.]+)</td>', numbers_ahead)

        if len(numbers) < 4:
            continue

        try:
            age = int(float(numbers[0]))
            gp = int(float(numbers[1]))
            gaa = float(numbers[2])
            sv_pct = float(numbers[3])

            if gp >= 10:
                goalies.append({
                    'name': name,
                    'team': team,
                    'age': age,
                    'gp': gp,
                    'gaa': gaa,
                    'sv_pct': sv_pct
                })
        except (ValueError, IndexError):
            continue

    # Add ranks
    sorted_goalies = sorted(goalies, key=lambda x: x['sv_pct'], reverse=True)
    for i, g in enumerate(sorted_goalies):
        g['rank'] = i + 1

    return sorted_goalies

def identify_candidates(goalies):
    """Identify hot goalies and pull candidates"""
    candidates = {'hot_goalies': [], 'pull_candidates': []}

    if not goalies:
        return candidates

    # Top 7 by SV%
    for g in goalies[:7]:
        candidates['hot_goalies'].append({
            'rank': g['rank'],
            'name': g['name'],
            'team': g['team'],
            'sv_pct': g['sv_pct'],
            'gaa': g['gaa'],
            'gp': g['gp'],
            'thesis': f"Top 7 SV% ({g['sv_pct']:.1%}) - OVER saves vs high-shot teams"
        })

    # Bottom 10 (SV% < 0.88)
    weak = [g for g in goalies if g['sv_pct'] < 0.88]
    for g in weak[:10]:
        candidates['pull_candidates'].append({
            'rank': g['rank'],
            'name': g['name'],
            'team': g['team'],
            'sv_pct': g['sv_pct'],
            'gaa': g['gaa'],
            'gp': g['gp'],
            'thesis': f"Weak SV% ({g['sv_pct']:.1%}) - UNDER saves / pull risk"
        })

    return candidates

def write_report(candidates):
    """Write daily misspricing report"""
    timestamp = datetime.now().strftime("%Y-%m-%d")
    filepath = f"/tmp/polymarket_hockey_{timestamp}.txt"

    with open(filepath, 'w') as f:
        f.write("=== POLYMARKET HOCKEY GOALIE MISSPRICES ===\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EST')}\n\n")

        f.write("[SCENARIO 1] HOT GOALIES - EXPECT OVERS\n")
        f.write("-" * 70 + "\n")
        f.write("Play: Goalie SAVES OVER in games vs high-shot teams\n")
        f.write("Rationale: Top 7 performers have elite SV%, should rack saves\n\n")

        for g in candidates['hot_goalies']:
            f.write(f"#{g['rank']} {g['name']:20} | {g['team']} | SV%: {g['sv_pct']:.1%} | GP: {g['gp']}\n")

        f.write("\n\n[SCENARIO 2] PULL CANDIDATES - EXPECT UNDERS\n")
        f.write("-" * 70 + "\n")
        f.write("Play: Goalie SAVES UNDER in games vs high-shot teams\n")
        f.write("Rationale: Weak SV% + high volume → backup pull + more goals\n\n")

        for g in candidates['pull_candidates']:
            f.write(f"#{g['rank']} {g['name']:20} | {g['team']} | SV%: {g['sv_pct']:.1%} | GP: {g['gp']}\n")

    print(f"✓ Report: {filepath}")
    return filepath

def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Hockey Scanner v3 started")

    html = fetch_quanthockey()
    goalies = parse_goalie_stats(html)

    print(f"Parsed {len(goalies)} goalies (GP >= 10)")

    if goalies:
        candidates = identify_candidates(goalies)

        print(f"Hot goalies: {len(candidates['hot_goalies'])}")
        for g in candidates['hot_goalies']:
            print(f"  #{g['rank']} {g['name']} ({g['team']}): {g['sv_pct']:.1%}")

        print(f"Pull candidates: {len(candidates['pull_candidates'])}")
        for g in candidates['pull_candidates']:
            print(f"  #{g['rank']} {g['name']} ({g['team']}): {g['sv_pct']:.1%}")

        write_report(candidates)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Hockey Scanner completed")
    else:
        print("Failed to parse goalies")

if __name__ == "__main__":
    main()
