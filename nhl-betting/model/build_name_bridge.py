
"""
Build a name bridge between sog_odds (bp_player_id, player_name, event_date)
and player_stats (player_id, game_id) via player_pp_stats (has player_name).
Steps: diagnose, name-match, fix mismatches, validate, export CSV.
"""

import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pandas as pd

from lib.db import get_conn


def normalize_name(name):
    """Normalize a player name for fuzzy matching."""
    if not name or not isinstance(name, str):
        return ""
    # Remove accents
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    # Handle "Lastname, Firstname" format
    if "," in s:
        parts = s.split(",", 1)
        s = f"{parts[1].strip()} {parts[0].strip()}"
    # Remove Jr., Sr., III, II, etc.
    s = re.sub(r"\b(jr\.?|sr\.?|iii|ii|iv)\b", "", s)
    # Remove periods, hyphens become spaces, collapse whitespace
    s = s.replace(".", "").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def step1_diagnose(conn):
    """Step 1: Diagnose the mismatch."""
    print("=" * 60)
    print("STEP 1: DIAGNOSE THE MISMATCH")
    print("=" * 60)

    cur = conn.cursor()

    # Sample sog_odds
    print("\n--- sog_odds sample ---")
    cur.execute(
        "SELECT event_id, event_date, player_name, line "
        "FROM sog_odds WHERE line IS NOT NULL "
        "ORDER BY event_date DESC LIMIT 10"
    )
    rows = cur.fetchall()
    print(f"{'event_id':<12} {'event_date':<12} {'player_name':<25} {'line':>6}")
    for r in rows:
        print(f"{r[0]:<12} {r[1]!s:<12} {r[2]:<25} {r[3]:>6}")

    # Sample player game log (using player_pp_stats which has player_name)
    print("\n--- player game log sample (player_pp_stats) ---")
    cur.execute(
        "SELECT pp.player_id, pp.player_name, g.game_date "
        "FROM player_pp_stats pp "
        "JOIN games g ON pp.game_id = g.game_id "
        "ORDER BY g.game_date DESC LIMIT 10"
    )
    rows = cur.fetchall()
    print(f"{'player_id':<12} {'player_name':<25} {'game_date':<12}")
    for r in rows:
        print(f"{r[0]:<12} {r[1]:<25} {r[2]!s:<12}")

    # ID ranges
    print("\n--- ID ranges ---")
    cur.execute("SELECT MIN(event_id), MAX(event_id) FROM sog_odds")
    eid_min, eid_max = cur.fetchone()
    cur.execute("SELECT MIN(game_id), MAX(game_id) FROM games")
    gid_min, gid_max = cur.fetchone()
    print(f"sog_odds.event_id range: {eid_min} to {eid_max}")
    print(f"games.game_id range:     {gid_min} to {gid_max}")
    same_scale = (
        abs(len(str(eid_min or 0)) - len(str(gid_min or 0))) <= 1
    )
    print(f"Same numeric scale? {'YES - could be same IDs' if same_scale else 'NO - different systems'}")

    # Direct event_id = game_id overlap test
    cur.execute(
        "SELECT COUNT(*) FROM sog_odds so "
        "JOIN games g ON so.event_id::bigint = g.game_id"
    )
    overlap = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT event_id) FROM sog_odds")
    total_events = cur.fetchone()[0]
    print(f"event_id directly matches game_id: {overlap}/{total_events}")

    # Date overlap
    print("\n--- Date overlap ---")
    cur.execute(
        "SELECT so.event_date, g.game_date, so.event_id, g.game_id "
        "FROM sog_odds so "
        "JOIN games g ON so.event_date = g.game_date "
        "LIMIT 5"
    )
    rows = cur.fetchall()
    if rows:
        print("event_date matches game_date — sample joins:")
        for r in rows:
            print(f"  sog_odds date={r[0]}, games date={r[1]}, event_id={r[2]}, game_id={r[3]}")
    else:
        print("No date overlaps found!")

    cur.execute(
        "SELECT MIN(event_date), MAX(event_date) FROM sog_odds"
    )
    so_min, so_max = cur.fetchone()
    cur.execute("SELECT MIN(game_date), MAX(game_date) FROM games")
    g_min, g_max = cur.fetchone()
    print(f"sog_odds date range: {so_min} to {so_max}")
    print(f"games date range:    {g_min} to {g_max}")

    print()


def step2_name_bridge(conn):
    """Step 2: Build name bridge via normalized name + date."""
    print("=" * 60)
    print("STEP 2: BUILD NAME BRIDGE")
    print("=" * 60)

    # Get distinct sog_odds player names with their bp_player_id
    sog = pd.read_sql(
        "SELECT DISTINCT bp_player_id, player_name FROM sog_odds "
        "WHERE player_name IS NOT NULL",
        conn,
    )
    sog["name_norm"] = sog["player_name"].apply(normalize_name)

    # Get distinct NHL player names with player_id
    nhl = pd.read_sql(
        "SELECT DISTINCT player_id, player_name FROM player_pp_stats "
        "WHERE player_name IS NOT NULL",
        conn,
    )
    nhl["name_norm"] = nhl["player_name"].apply(normalize_name)

    print(f"sog_odds distinct players: {len(sog)}")
    print(f"NHL distinct players:      {len(nhl)}")

    # Join on normalized name
    merged = sog.merge(nhl, on="name_norm", how="left", suffixes=("_sog", "_nhl"))

    matched = merged[merged["player_id"].notna()]
    unmatched = merged[merged["player_id"].isna()]

    print(f"\nMatched: {len(matched)} / {len(sog)} players ({len(matched)/len(sog)*100:.1f}%)")
    print(f"Unmatched: {len(unmatched)}")

    # Now check row-level match rate
    total_sog = pd.read_sql("SELECT COUNT(*) as n FROM sog_odds", conn).iloc[0]["n"]
    matched_ids = set(matched["bp_player_id"].unique())
    matched_rows = pd.read_sql(
        f"SELECT COUNT(*) as n FROM sog_odds WHERE bp_player_id IN ({','.join(str(x) for x in matched_ids)})",
        conn,
    ).iloc[0]["n"]
    print(f"\nRow-level: {matched_rows:,} / {total_sog:,} sog_odds rows have a player_id match ({matched_rows/total_sog*100:.1f}%)")

    return merged, unmatched


def step3_fix_mismatches(conn, unmatched_df):
    """Step 3: Handle remaining mismatches with manual corrections."""
    print("\n" + "=" * 60)
    print("STEP 3: FIX REMAINING MISMATCHES")
    print("=" * 60)

    # Get unmatched names
    unmatched_names = unmatched_df[["player_name_sog", "name_norm"]].drop_duplicates()

    # Count how many odds rows each unmatched name has
    unmatched_counts = pd.read_sql(
        "SELECT player_name, COUNT(*) as n FROM sog_odds GROUP BY player_name",
        conn,
    )
    unmatched_names = unmatched_names.merge(
        unmatched_counts,
        left_on="player_name_sog",
        right_on="player_name",
        how="left",
    )
    unmatched_names = unmatched_names.sort_values("n", ascending=False)

    print("\nTop 20 unmatched player names:")
    print(f"{'player_name':<35} {'normalized':<30} {'odds_rows':>10}")
    print("-" * 77)
    top20 = unmatched_names.head(20)
    for _, row in top20.iterrows():
        print(f"{row['player_name_sog']:<35} {row['name_norm']:<30} {row['n']:>10,.0f}")

    # Get all NHL names for fuzzy matching
    nhl_names = pd.read_sql(
        "SELECT DISTINCT player_id, player_name FROM player_pp_stats",
        conn,
    )
    nhl_lookup = {normalize_name(n): (pid, n) for pid, n in zip(nhl_names["player_id"], nhl_names["player_name"])}

    # Build manual corrections by trying common transformations
    corrections = {}
    for _, row in unmatched_names.iterrows():
        sog_name = row["player_name_sog"]
        norm = row["name_norm"]
        if not norm:
            continue

        # Try last-name-only match (risky but flag it)
        parts = norm.split()
        if len(parts) >= 2:
            # Try swapping common nicknames
            nick_map = {
                "alex": "alexander",
                "alexander": "alex",
                "mike": "michael",
                "michael": "mike",
                "matt": "matthew",
                "matthew": "matt",
                "nick": "nicholas",
                "nicholas": "nick",
                "jake": "jacob",
                "jacob": "jake",
                "zach": "zachary",
                "zachary": "zach",
                "jon": "jonathan",
                "jonathan": "jon",
                "chris": "christopher",
                "christopher": "chris",
                "tj": "t j",
                "jt": "j t",
                "pj": "p j",
                "aj": "a j",
                "jj": "j j",
                "jp": "j p",
            }
            first = parts[0]
            last = " ".join(parts[1:])

            # Try nickname swap
            if first in nick_map:
                alt = f"{nick_map[first]} {last}"
                if alt in nhl_lookup:
                    corrections[sog_name] = nhl_lookup[alt]
                    continue

            # Try removing/adding spaces in hyphenated names
            no_space = norm.replace(" ", "")
            for nhl_norm, (pid, pname) in nhl_lookup.items():
                if nhl_norm.replace(" ", "") == no_space:
                    corrections[sog_name] = (pid, pname)
                    break

    print(f"\nAuto-corrections found: {len(corrections)}")
    for sog_name, (pid, nhl_name) in list(corrections.items())[:15]:
        print(f"  '{sog_name}' → '{nhl_name}' (id={pid})")

    # Now rebuild full bridge with corrections
    sog = pd.read_sql(
        "SELECT DISTINCT bp_player_id, player_name FROM sog_odds WHERE player_name IS NOT NULL",
        conn,
    )
    sog["name_norm"] = sog["player_name"].apply(normalize_name)

    nhl = pd.read_sql(
        "SELECT DISTINCT player_id, player_name FROM player_pp_stats WHERE player_name IS NOT NULL",
        conn,
    )
    nhl["name_norm"] = nhl["player_name"].apply(normalize_name)

    # Apply corrections: override name_norm for corrected names
    correction_norm_map = {}
    for sog_name, (pid, nhl_name) in corrections.items():
        correction_norm_map[normalize_name(sog_name)] = normalize_name(nhl_name)

    sog["name_norm_fixed"] = sog["name_norm"].map(
        lambda x: correction_norm_map.get(x, x)
    )
    nhl["name_norm_fixed"] = nhl["name_norm"]

    merged = sog.merge(
        nhl,
        left_on="name_norm_fixed",
        right_on="name_norm",
        how="left",
        suffixes=("_sog", "_nhl"),
    )

    matched = merged[merged["player_id"].notna()]
    still_unmatched = merged[merged["player_id"].isna()]

    total_sog_rows = pd.read_sql("SELECT COUNT(*) as n FROM sog_odds", conn).iloc[0]["n"]
    matched_ids = set(matched["bp_player_id"].unique())
    if matched_ids:
        matched_rows = pd.read_sql(
            f"SELECT COUNT(*) as n FROM sog_odds WHERE bp_player_id IN ({','.join(str(x) for x in matched_ids)})",
            conn,
        ).iloc[0]["n"]
    else:
        matched_rows = 0

    print("\nFinal match rate:")
    print(f"  Players: {len(matched)} / {len(sog)} ({len(matched)/len(sog)*100:.1f}%)")
    print(f"  Rows:    {matched_rows:,} / {total_sog_rows:,} ({matched_rows/total_sog_rows*100:.1f}%)")

    if len(still_unmatched) > 0:
        print(f"\nStill unmatched ({len(still_unmatched)}):")
        for _, row in still_unmatched.head(10).iterrows():
            print(f"  {row['player_name_sog']}")

    return matched


def step4_validate_and_export(conn, matched_df):
    """Step 4: Validate and export bridge table."""
    print("\n" + "=" * 60)
    print("STEP 4: VALIDATE AND EXPORT")
    print("=" * 60)

    # Build bridge: bp_player_id -> player_id
    bridge = matched_df[["bp_player_id", "player_id", "player_name_sog", "player_name_nhl"]].copy()
    bridge = bridge.drop_duplicates(subset=["bp_player_id"])
    bridge["player_id"] = bridge["player_id"].astype(int)

    # Validate line values
    lines = pd.read_sql(
        "SELECT bp_player_id, player_name, line FROM sog_odds WHERE line IS NOT NULL",
        conn,
    )
    lines_with_id = lines.merge(
        bridge[["bp_player_id", "player_id"]],
        on="bp_player_id",
        how="inner",
    )

    print("\nLine value distribution (matched rows):")
    print(f"  Min:    {lines_with_id['line'].min()}")
    print(f"  Max:    {lines_with_id['line'].max()}")
    print(f"  Mean:   {lines_with_id['line'].mean():.2f}")
    print(f"  Median: {lines_with_id['line'].median()}")

    out_of_range = lines_with_id[
        (lines_with_id["line"] < 0.5) | (lines_with_id["line"] > 8.5)
    ]
    print(f"  Out of range (<0.5 or >8.5): {len(out_of_range)} rows")

    # Spot check 5 known players
    spot_checks = ["Connor McDavid", "Auston Matthews", "Nathan MacKinnon", "Leon Draisaitl", "Nikita Kucherov"]
    print("\n--- Spot checks ---")
    for name in spot_checks:
        sub = lines_with_id[lines_with_id["player_name"].str.contains(name.split()[-1], case=False, na=False)]
        if len(sub) > 0:
            avg_line = sub["line"].mean()
            min_line = sub["line"].min()
            max_line = sub["line"].max()
            pid = sub["player_id"].iloc[0]
            print(f"  {name} (id={pid}): avg_line={avg_line:.2f}, range=[{min_line}, {max_line}], n={len(sub)}")
        else:
            print(f"  {name}: NOT FOUND in matched data")

    # Export
    out_path = str(Path(__file__).resolve().parent / "player_odds_bridge.csv")
    bridge.to_csv(out_path, index=False)
    print(f"\nBridge exported: {out_path}")
    print(f"  {len(bridge)} unique player mappings")

    return bridge


def main():
    conn = get_conn(db="nhl_betting")
    step1_diagnose(conn)
    merged, unmatched = step2_name_bridge(conn)
    matched = step3_fix_mismatches(conn, unmatched)
    step4_validate_and_export(conn, matched)
    conn.close()
    print("\nDone ✅")


if __name__ == "__main__":
    main()
