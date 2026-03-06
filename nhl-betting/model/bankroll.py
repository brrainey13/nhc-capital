"""Shared bankroll helpers for NHL pick sizing and ledger writes."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

import psycopg2

try:
    from .db_config import get_dsn
except ImportError:
    from db_config import get_dsn

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
UNIT_RATE = Decimal("0.01")


def _to_decimal(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def quantize_money(value: Decimal | float | int | str) -> Decimal:
    """Round a numeric value to two decimal places."""
    return _to_decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def get_current_bankroll(dsn: str | None = None) -> Decimal:
    """Return the most recent bankroll balance from Postgres."""
    conn = psycopg2.connect(dsn or get_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM bankroll ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            if not row or row[0] is None:
                return ZERO
            return quantize_money(row[0])
    finally:
        conn.close()


def get_unit_size(bankroll: Decimal | float | int | None = None) -> Decimal:
    """Return the current 1% unit size."""
    current = _to_decimal(bankroll) if bankroll is not None else get_current_bankroll()
    return quantize_money(current * UNIT_RATE)


def kelly_size(
    *,
    odds: int | float,
    fraction: float = 0.25,
    bankroll: Decimal | float | int | None = None,
    win_prob: float | None = None,
    edge: float | None = None,
) -> tuple[float, float]:
    """Return (units, dollars) using a 1% unit and fractional Kelly sizing."""
    current_bankroll = (
        _to_decimal(bankroll) if bankroll is not None else get_current_bankroll()
    )
    if current_bankroll <= 0:
        return 0.0, 0.0

    if odds > 0:
        payout = Decimal(str(odds)) / Decimal("100")
        implied = Decimal("100") / (Decimal(str(odds)) + Decimal("100"))
    else:
        payout = Decimal("100") / Decimal(str(abs(odds)))
        implied = Decimal(str(abs(odds))) / (Decimal(str(abs(odds))) + Decimal("100"))

    if win_prob is None:
        if edge is None:
            raise ValueError("kelly_size requires win_prob or edge")
        probability = implied + Decimal(str(edge))
    else:
        probability = Decimal(str(win_prob))

    if probability <= 0 or probability >= 1:
        return 0.0, 0.0

    lose_prob = Decimal("1") - probability
    base_fraction = (payout * probability - lose_prob) / payout
    if base_fraction <= 0:
        return 0.0, 0.0

    applied_fraction = base_fraction * Decimal(str(fraction))
    dollars = quantize_money(current_bankroll * applied_fraction)
    unit_size = get_unit_size(current_bankroll)
    if dollars <= 0 or unit_size <= 0:
        return 0.0, 0.0

    units = (dollars / unit_size).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(units), float(dollars)


def get_latest_balance(cur, *, lock: bool = False) -> Decimal:
    """Read the most recent balance from the bankroll ledger."""
    sql = "SELECT balance FROM bankroll ORDER BY id DESC LIMIT 1"
    if lock:
        sql += " FOR UPDATE"
    cur.execute(sql)
    row = cur.fetchone()
    if not row or row[0] is None:
        return ZERO
    return quantize_money(row[0])


def append_bankroll_event(
    cur,
    *,
    event_date,
    event_type: str,
    amount: Decimal | float | int | str,
    pick_id: int | None = None,
    sportsbook: str | None = None,
    notes: str | None = None,
) -> tuple[int, Decimal]:
    """Insert a bankroll ledger row and return (id, new_balance)."""
    latest_balance = get_latest_balance(cur, lock=True)
    amount_value = quantize_money(amount)
    new_balance = quantize_money(latest_balance + amount_value)
    cur.execute(
        """
        INSERT INTO bankroll (
            event_date,
            event_type,
            amount,
            balance,
            pick_id,
            sportsbook,
            notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id, balance
        """,
        (
            event_date,
            event_type,
            amount_value,
            new_balance,
            pick_id,
            sportsbook,
            notes,
        ),
    )
    ledger_id, balance = cur.fetchone()
    return ledger_id, quantize_money(balance)
