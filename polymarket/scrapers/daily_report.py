#!/usr/bin/env python3
"""Polymarket Daily Report — prints a clean summary to stdout."""

import os
import subprocess
from datetime import datetime, timedelta

import psycopg2

DB = {
    "host": "localhost",
    "database": "clawd",
    "user": "clawd_user",
    "password": os.environ.get("CLAWD_DB_PASSWORD", ""),
}

def run(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()

def main():
    now = datetime.now()
    ago24 = now - timedelta(hours=24)
    print("📊 **Polymarket Daily Report**")
    print(f"🕐 {now.strftime('%a %b %d, %Y %H:%M %Z')}")
    print()

    # 1. Disk usage
    print("💾 **Disk Usage**")
    df_line = run("df -h / | tail -1")
    parts = df_line.split()
    print(f"  Root: {parts[2]} used / {parts[1]} total ({parts[4]})")
    pg_size = run("sudo du -sh /var/lib/postgresql 2>/dev/null || echo 'N/A'").split()[0]
    home_size = run("du -sh /home/brainey/polymarket 2>/dev/null || echo 'N/A'").split()[0]
    print(f"  PostgreSQL data: {pg_size}")
    print(f"  ~/polymarket: {home_size}")
    print()

    # DB queries
    conn = psycopg2.connect(**DB)
    cur = conn.cursor()

    # 2. Row counts
    print("📋 **Table Row Counts**")
    tables = ['markets', 'market_snapshots', 'positions', 'theses', 'agent_log', 'human_notes']
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        cnt = cur.fetchone()[0]
        print(f"  {t}: {cnt:,}")
    print()

    # 3. Last 24h activity
    print("📥 **Last 24h Activity**")
    cur.execute("SELECT COUNT(*) FROM market_snapshots WHERE snapshot_time >= %s", (ago24,))
    new_snaps = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM markets WHERE last_updated >= %s", (ago24,))
    updated_mkts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM markets WHERE created_at >= %s", (ago24,))
    new_mkts = cur.fetchone()[0]
    print(f"  New snapshots: {new_snaps:,}")
    print(f"  New markets: {new_mkts:,}")
    print(f"  Updated markets: {updated_mkts:,}")
    print()

    # 4. Top 5 by volume
    print("🏆 **Top 5 Markets by 24h Volume**")
    cur.execute("""
        SELECT question, volume_24h, yes_price
        FROM markets WHERE volume_24h IS NOT NULL
        ORDER BY volume_24h DESC LIMIT 5
    """)
    for i, (q, vol, yp) in enumerate(cur.fetchall(), 1):
        q_short = (q[:60] + "…") if len(q) > 60 else q
        price_str = f"{yp:.0%}" if yp is not None else "?"
        vol_str = f"${vol:,.0f}" if vol else "$0"
        print(f"  {i}. {q_short}")
        print(f"     Yes: {price_str} | Vol: {vol_str}")
    print()

    # 5. Data gaps (hours with no snapshots in last 24h)
    print("⚠️ **Data Collection Gaps (last 24h)**")
    cur.execute("""
        WITH hours AS (
            SELECT generate_series(
                date_trunc('hour', %s),
                date_trunc('hour', %s),
                '1 hour'::interval
            ) AS hr
        )
        SELECT hr FROM hours h
        WHERE NOT EXISTS (
            SELECT 1 FROM market_snapshots ms
            WHERE ms.snapshot_time >= h.hr AND ms.snapshot_time < h.hr + '1 hour'::interval
        )
        ORDER BY hr
    """, (ago24, now))
    gaps = cur.fetchall()
    if gaps:
        for (hr,) in gaps:
            print(f"  ❌ {hr.strftime('%b %d %H:%M')}")
        print(f"  {len(gaps)} hour(s) missing")
    else:
        print("  ✅ No gaps — all hours have data")

    conn.close()
    print()
    print("— end of report —")

if __name__ == "__main__":
    main()
