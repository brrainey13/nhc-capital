"""NHL bankroll tracking endpoints."""

from __future__ import annotations

from decimal import Decimal

from db import get_pool
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from routes.ingest import _get_etl_pool

router = APIRouter(prefix="/api/nhl/bankroll", tags=["nhl-bankroll"])


class BankrollAdjustmentRequest(BaseModel):
    amount: float = Field(gt=0)
    sportsbook: str = "DraftKings"
    notes: str | None = None


def _money(value) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01")))


@router.get("")
async def get_bankroll():
    pool = get_pool("bankroll")
    current = await pool.fetchrow(
        """
        SELECT balance, event_date, created_at
        FROM bankroll
        ORDER BY id DESC
        LIMIT 1
        """
    )
    transactions = await pool.fetch(
        """
        SELECT id, event_date, event_type, amount, balance, pick_id,
               sportsbook, notes, created_at
        FROM bankroll
        ORDER BY id DESC
        LIMIT 100
        """
    )
    return {
        "current_balance": _money(current["balance"]) if current else 0.0,
        "as_of_date": str(current["event_date"]) if current else None,
        "updated_at": current["created_at"].isoformat() if current else None,
        "transactions": [
            {
                "id": row["id"],
                "event_date": str(row["event_date"]),
                "event_type": row["event_type"],
                "amount": _money(row["amount"]),
                "balance": _money(row["balance"]),
                "pick_id": row["pick_id"],
                "sportsbook": row["sportsbook"],
                "notes": row["notes"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in transactions
        ],
    }


async def _create_adjustment(req: BankrollAdjustmentRequest, *, event_type: str, sign: int):
    pool = await _get_etl_pool("nhl_betting")
    amount = Decimal(str(req.amount)).quantize(Decimal("0.01")) * sign
    async with pool.acquire() as conn:
        async with conn.transaction():
            latest = await conn.fetchrow(
                """
                SELECT balance
                FROM bankroll
                ORDER BY id DESC
                LIMIT 1
                FOR UPDATE
                """
            )
            current_balance = Decimal(str(latest["balance"])) if latest else Decimal("0.00")
            new_balance = (current_balance + amount).quantize(Decimal("0.01"))
            if event_type == "withdrawal" and new_balance < 0:
                raise HTTPException(400, "Withdrawal would make bankroll negative.")

            row = await conn.fetchrow(
                """
                INSERT INTO bankroll (
                    event_date,
                    event_type,
                    amount,
                    balance,
                    sportsbook,
                    notes
                )
                VALUES (CURRENT_DATE, $1, $2, $3, $4, $5)
                RETURNING id, event_date, event_type, amount, balance, sportsbook, notes, created_at
                """,
                event_type,
                amount,
                new_balance,
                req.sportsbook,
                req.notes,
            )

    return {
        "id": row["id"],
        "event_date": str(row["event_date"]),
        "event_type": row["event_type"],
        "amount": _money(row["amount"]),
        "balance": _money(row["balance"]),
        "sportsbook": row["sportsbook"],
        "notes": row["notes"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


@router.post("/deposit")
async def create_deposit(req: BankrollAdjustmentRequest):
    return await _create_adjustment(req, event_type="deposit", sign=1)


@router.post("/withdrawal")
async def create_withdrawal(req: BankrollAdjustmentRequest):
    return await _create_adjustment(req, event_type="withdrawal", sign=-1)


@router.get("/summary")
async def get_bankroll_summary():
    pool = get_pool("bankroll")

    current = await pool.fetchrow(
        """
        SELECT balance
        FROM bankroll
        ORDER BY id DESC
        LIMIT 1
        """
    )
    daily_rows = await pool.fetch(
        """
        WITH graded AS (
            SELECT event_date, COALESCE(SUM(amount), 0) AS daily_pl
            FROM bankroll
            WHERE event_type = 'bet_graded'
            GROUP BY event_date
        ),
        balances AS (
            SELECT DISTINCT ON (event_date)
                   event_date,
                   balance
            FROM bankroll
            ORDER BY event_date, id DESC
        )
        SELECT b.event_date,
               COALESCE(g.daily_pl, 0) AS daily_pl,
               b.balance
        FROM balances b
        LEFT JOIN graded g USING (event_date)
        ORDER BY b.event_date
        """
    )
    pick_stats = await pool.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (WHERE result = 'W') AS wins,
            COUNT(*) FILTER (WHERE result = 'L') AS losses,
            COUNT(*) FILTER (WHERE result IN ('W', 'L')) AS graded_bets,
            COALESCE(SUM(pnl) FILTER (WHERE result IN ('W', 'L')), 0) AS total_pl,
            COALESCE(SUM(dollars) FILTER (WHERE result IN ('W', 'L')), 0) AS total_staked
        FROM nhl_picks
        """
    )

    wins = int(pick_stats["wins"] or 0)
    losses = int(pick_stats["losses"] or 0)
    graded_bets = int(pick_stats["graded_bets"] or 0)
    total_staked = _money(pick_stats["total_staked"])
    total_pl = _money(pick_stats["total_pl"])

    return {
        "current_balance": _money(current["balance"]) if current else 0.0,
        "daily_pl": [
            {
                "date": str(row["event_date"]),
                "pnl": _money(row["daily_pl"]),
            }
            for row in daily_rows
        ],
        "balance_chart": [
            {
                "date": str(row["event_date"]),
                "balance": _money(row["balance"]),
            }
            for row in daily_rows
        ],
        "wins": wins,
        "losses": losses,
        "graded_bets": graded_bets,
        "win_rate": round((wins / graded_bets) * 100, 1) if graded_bets else 0.0,
        "roi": round((total_pl / total_staked) * 100, 1) if total_staked else 0.0,
        "total_pl": total_pl,
        "total_staked": total_staked,
    }


@router.get("/history")
async def get_bankroll_history():
    pool = get_pool("bankroll")
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (event_date)
               event_date,
               balance
        FROM bankroll
        ORDER BY event_date, id DESC
        """
    )
    return [
        {
            "date": str(row["event_date"]),
            "balance": _money(row["balance"]),
        }
        for row in rows
    ]
