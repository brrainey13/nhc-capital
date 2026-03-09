"""Bankroll management utility — reset, deposit, withdraw, status.

Usage:
    scripts/db-etl nhl-betting/scripts/bankroll_manage.py reset 500
    scripts/db-etl nhl-betting/scripts/bankroll_manage.py deposit 500 "Weekly reload"
    scripts/db-etl nhl-betting/scripts/bankroll_manage.py status
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Add nhl-betting to path for model imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg2
from model.bankroll import append_bankroll_event, get_latest_balance, quantize_money
from model.db_config import get_dsn


def reset_bankroll(starting_amount: str, note: str = "") -> None:
    """Archive all existing entries and start fresh with a deposit."""
    amount = quantize_money(starting_amount)
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            # Archive old entries
            cur.execute(
                """UPDATE bankroll
                   SET notes = CONCAT('[ARCHIVED] ', COALESCE(notes, ''))
                   WHERE notes IS NULL OR notes NOT LIKE '[ARCHIVED]%%';"""
            )
            archived = cur.rowcount
            print(f"Archived {archived} previous bankroll entries")

            # Insert fresh deposit
            reason = note or f"Bankroll reset to ${amount}"
            ledger_id, balance = append_bankroll_event(
                cur,
                event_date=date.today(),
                event_type="deposit",
                amount=amount,
                notes=reason,
            )
            print(f"New deposit: ${amount} (ledger #{ledger_id}, balance: ${balance})")
        conn.commit()
    finally:
        conn.close()


def deposit(amount_str: str, note: str = "") -> None:
    """Add funds to the bankroll."""
    amount = quantize_money(amount_str)
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            reason = note or f"Deposit ${amount}"
            ledger_id, balance = append_bankroll_event(
                cur,
                event_date=date.today(),
                event_type="deposit",
                amount=amount,
                notes=reason,
            )
            print(f"Deposited ${amount} (ledger #{ledger_id}, balance: ${balance})")
        conn.commit()
    finally:
        conn.close()


def status() -> None:
    """Print current bankroll status."""
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            balance = get_latest_balance(cur)
            cur.execute(
                """SELECT COUNT(*), MIN(event_date), MAX(event_date)
                   FROM bankroll
                   WHERE notes IS NULL OR notes NOT LIKE '[ARCHIVED]%%';"""
            )
            count, first, last = cur.fetchone()
            print(f"Balance: ${balance}")
            print(f"Active entries: {count}")
            print(f"Date range: {first} → {last}")
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: bankroll_manage.py <reset|deposit|status> [amount] [note]")
        sys.exit(1)

    action = sys.argv[1]
    if action == "reset":
        if len(sys.argv) < 3:
            print("Usage: bankroll_manage.py reset <amount> [note]")
            sys.exit(1)
        reset_bankroll(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    elif action == "deposit":
        if len(sys.argv) < 3:
            print("Usage: bankroll_manage.py deposit <amount> [note]")
            sys.exit(1)
        deposit(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    elif action == "status":
        status()
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
