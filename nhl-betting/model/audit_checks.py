"""Audit checks 1-5: matrix stats, cross-reference, duplicates, pulls, splits."""

import psycopg2
from audit_utils import DB


# ── CHECK 1: Matrix stats ──
def check1(df):
    print("=" * 70)
    print("CHECK 1: FEATURE MATRIX STATS")
    print("=" * 70)
    print(f"Rows: {len(df)}")
    print(f"Columns: {len(df.columns)}")
    print(f"Date range: {df['event_date'].min().date()} to {df['event_date'].max().date()}")

    goalie_col = None
    for c in ["player_name", "goalie_name", "player_id", "goalie_id"]:
        if c in df.columns:
            goalie_col = c
            break
    if goalie_col:
        print(f"Unique goalies ({goalie_col}): {df[goalie_col].nunique()}")
    else:
        print("No obvious goalie ID column found. Columns containing 'player' or 'goalie':")
        print([c for c in df.columns if "player" in c.lower() or "goalie" in c.lower()])

    print("\nNull % per column (showing >0% only):")
    null_pct = (df.isnull().sum() / len(df) * 100).round(2)
    non_zero = null_pct[null_pct > 0].sort_values(ascending=False)
    if len(non_zero) == 0:
        print("  No nulls in any column")
    else:
        for col, pct in non_zero.items():
            print(f"  {col}: {pct}%")
    print()


# ── CHECK 2: Cross-reference 5 random rows ──
def check2(df):
    print("=" * 70)
    print("CHECK 2: CROSS-REFERENCE 5 RANDOM ROWS VS SOURCE TABLES")
    print("=" * 70)
    conn = psycopg2.connect(DB)

    sample = df.sample(5, random_state=42)

    for i, (idx, row) in enumerate(sample.iterrows()):
        print(f"\n--- Row {i+1} ---")
        date = row["event_date"]
        player = row.get("player_name", "unknown")
        line = row.get("line", None)
        saves = row.get("saves", None)
        sa = row.get("shots_against", None)

        print(f"  Matrix: date={date.date()}, player={player}, line={line}, saves={saves}, shots_against={sa}")

        cur = conn.cursor()
        cur.execute(
            "SELECT player_name, line, event_date FROM saves_odds WHERE player_name ILIKE %s AND event_date::date = %s::date LIMIT 3",
            (f"%{player.split()[-1]}%", str(date.date())),
        )
        odds_rows = cur.fetchall()
        if odds_rows:
            for r in odds_rows:
                print(f"  saves_odds: player={r[0]}, line={r[1]}, date={r[2]}")
                if line is not None and r[1] is not None:
                    match = "✅" if abs(float(line) - float(r[1])) < 0.01 else "⚠️ MISMATCH"
                    print(f"    Line check: matrix={line}, source={r[1]} {match}")
        else:
            print(f"  saves_odds: NO MATCH found for {player} on {date.date()}")

        cur.execute(
            "SELECT gs.saves, gs.shots_against, g.game_date "
            "FROM goalie_stats gs "
            "JOIN games g ON gs.game_id = g.game_id "
            "JOIN players p ON gs.player_id = p.player_id "
            "WHERE p.last_name ILIKE %s AND g.game_date::date = %s::date LIMIT 3",
            (f"%{player.split()[-1]}%", str(date.date())),
        )
        gs_rows = cur.fetchall()
        if gs_rows:
            for r in gs_rows:
                sa_match = "✅" if sa is not None and r[1] is not None and int(sa) == int(r[1]) else "⚠️"
                sv_match = "✅" if saves is not None and r[0] is not None and int(saves) == int(r[0]) else "⚠️"
                print(f"  goalie_stats: saves={r[0]}{sv_match}, shots_against={r[1]}{sa_match}, date={r[2]}")
        else:
            print(f"  goalie_stats: NO MATCH for {player} on {date.date()}")

    conn.close()
    print()


# ── CHECK 3: Duplicate rows ──
def check3(df):
    print("=" * 70)
    print("CHECK 3: DUPLICATE GOALIE + DATE ROWS")
    print("=" * 70)
    id_cols = []
    for c in ["player_name", "player_id", "goalie_id"]:
        if c in df.columns:
            id_cols.append(c)
            break
    id_cols.append("event_date")

    dupes = df.duplicated(subset=id_cols, keep=False)
    n_dupes = dupes.sum()
    print(f"Duplicate rows on {id_cols}: {n_dupes}")
    if n_dupes > 0:
        dupe_df = df[dupes].sort_values(id_cols)
        print("Sample duplicates:")
        print(dupe_df[id_cols + ["line", "saves"]].head(10).to_string())
    else:
        print("✅ No duplicates")
    print()


# ── CHECK 4: Pulled goalies ──
def check4(df):
    print("=" * 70)
    print("CHECK 4: PULLED GOALIES / SHORTENED STARTS")
    print("=" * 70)
    if "was_pulled" in df.columns:
        pulled = df["was_pulled"].sum()
        pct = pulled / len(df) * 100
        print(f"Pulled games: {int(pulled)} / {len(df)} ({pct:.1f}%)")

        pulled_df = df[df["was_pulled"] == 1]
        normal_df = df[df["was_pulled"] != 1]
        print(f"  Pulled: avg saves={pulled_df['saves'].mean():.1f}, avg SA={pulled_df['shots_against'].mean():.1f}")
        print(f"  Normal: avg saves={normal_df['saves'].mean():.1f}, avg SA={normal_df['shots_against'].mean():.1f}")

        if "line" in df.columns:
            pulled_with_line = pulled_df["line"].notna().sum()
            print(f"  Pulled games with odds lines: {pulled_with_line}")
            print("  → Pulled games ARE included in backtest (realistic — books don't know in advance)")
    else:
        print("No 'was_pulled' column. Checking for proxies...")
        if "saves" in df.columns and "shots_against" in df.columns:
            low_sa = df[df["shots_against"] < 15]
            print(f"  Games with <15 shots against (likely pulled/shortened): {len(low_sa)} ({len(low_sa)/len(df)*100:.1f}%)")
    print()


# ── CHECK 5: Train/test splits — no leakage ──
def check5(df):
    print("=" * 70)
    print("CHECK 5: EXACT TRAIN/TEST DATE SPLITS")
    print("=" * 70)
    splits = [
        {
            "name": "Fold 1: Train 22-23, Val 23-24",
            "train": df[df["event_date"] < "2023-10-01"],
            "val": df[(df["event_date"] >= "2023-10-01") & (df["event_date"] < "2024-10-01")],
        },
        {
            "name": "Fold 2: Train 22-24, Val 24-25",
            "train": df[df["event_date"] < "2024-10-01"],
            "val": df[(df["event_date"] >= "2024-10-01") & (df["event_date"] < "2025-10-01")],
        },
        {
            "name": "Fold 3: Train 22-25, Val 25-26",
            "train": df[df["event_date"] < "2025-10-01"],
            "val": df[df["event_date"] >= "2025-10-01"],
        },
    ]

    for s in splits:
        tr, va = s["train"], s["val"]
        if len(tr) == 0 or len(va) == 0:
            print(f"\n{s['name']}: SKIPPED (empty)")
            continue
        tr_max = tr["event_date"].max()
        va_min = va["event_date"].min()
        gap_days = (va_min - tr_max).days
        leak = "⚠️ LEAK!" if tr_max >= va_min else "✅ No leak"
        print(f"\n{s['name']}:")
        print(f"  Train: {tr['event_date'].min().date()} → {tr_max.date()} ({len(tr)} rows)")
        print(f"  Val:   {va_min.date()} → {va['event_date'].max().date()} ({len(va)} rows)")
        print(f"  Gap: {gap_days} days {leak}")
    print()
    return splits
