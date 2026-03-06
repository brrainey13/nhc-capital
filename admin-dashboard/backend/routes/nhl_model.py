"""NHL model outputs endpoints."""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

from db import get_pool, get_table_columns
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/nhl", tags=["nhl-model"])

ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / "nhl-betting" / "model"
ODDS_HISTORY_DATE_EXPR = "event_date::date"
TEXT_DATE_FMT = "YYYY-MM-DD"


def _num(value: Any) -> float:
    if value is None:
        return 0.0
    return round(float(value), 4)


def _parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    for parser in (datetime.fromisoformat, date.fromisoformat):
        try:
            return parser(text).date().isoformat() if parser is datetime.fromisoformat else parser(text).isoformat()
        except ValueError:
            continue
    return text[:10] if len(text) >= 10 else text


def _load_feature_importance_csv(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            feature = row[0].strip()
            if not feature:
                continue
            try:
                importance = float(row[1])
            except ValueError:
                continue
            rows.append({"feature": feature, "importance": importance})
    rows.sort(key=lambda item: item["importance"], reverse=True)
    return rows


def _load_model_info_sync() -> dict[str, Any]:
    if not MODEL_DIR.exists():
        return {
            "model_type": "LightGBM",
            "model_path": None,
            "model_found": False,
            "n_features": 0,
            "n_training_samples": 0,
            "feature_importances": [],
            "training_date": None,
        }

    metadata_path = MODEL_DIR / "model_metadata.json"
    feature_json_path = MODEL_DIR / "points_05_features.json"
    feature_csv_path = MODEL_DIR / "points_05_feature_importance.csv"
    artifact_candidates = [
        MODEL_DIR / "points_05_lgbm.pkl",
        MODEL_DIR / "points_15_v2_lgbm.pkl",
        MODEL_DIR / "lightgbm_model.pkl",
    ]

    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())

    feature_list: list[str] = []
    if feature_json_path.exists():
        try:
            parsed = json.loads(feature_json_path.read_text())
            if isinstance(parsed, list):
                feature_list = [str(item) for item in parsed]
            elif isinstance(parsed, dict) and isinstance(parsed.get("features"), list):
                feature_list = [str(item) for item in parsed["features"]]
        except json.JSONDecodeError:
            feature_list = []
    elif isinstance(metadata.get("features"), list):
        feature_list = [str(item) for item in metadata["features"]]

    feature_importances: list[dict[str, Any]] = []
    if feature_csv_path.exists():
        feature_importances = _load_feature_importance_csv(feature_csv_path)
    elif isinstance(metadata.get("feature_importances"), dict):
        feature_importances = sorted(
            (
                {"feature": str(feature), "importance": float(importance)}
                for feature, importance in metadata["feature_importances"].items()
            ),
            key=lambda item: item["importance"],
            reverse=True,
        )

    model_path = next((path for path in artifact_candidates if path.exists()), None)
    training_range = metadata.get("training_date_range") or []
    training_date = _parse_iso_date(training_range[-1] if training_range else None)
    if not training_date:
        training_date = _parse_iso_date(metadata.get("trained_at"))
    if not training_date and model_path:
        training_date = datetime.fromtimestamp(model_path.stat().st_mtime).date().isoformat()
    training_rows = int(metadata.get("training_rows") or metadata.get("row_count") or 0)
    n_features = len(feature_list) or len(feature_importances)

    return {
        "model_type": "LightGBM",
        "model_path": str(model_path) if model_path else None,
        "model_found": model_path is not None or bool(feature_importances or feature_list or metadata),
        "n_features": n_features,
        "n_training_samples": training_rows,
        "feature_importances": [
            {"feature": item["feature"], "importance": _num(item["importance"])}
            for item in feature_importances
        ],
        "training_date": training_date,
        "artifacts": {
            "metadata_path": str(metadata_path) if metadata_path.exists() else None,
            "feature_importance_path": str(feature_csv_path) if feature_csv_path.exists() else None,
        },
    }


async def _pick_strategy_expr() -> str:
    columns = await get_table_columns("nhl_picks")
    if "sub_strategy" in columns:
        return "COALESCE(NULLIF(sub_strategy, ''), NULLIF(confidence, ''), 'Unlabeled')"
    if "strategy" in columns:
        return "COALESCE(NULLIF(strategy, ''), NULLIF(confidence, ''), 'Unlabeled')"
    return "COALESCE(NULLIF(confidence, ''), 'Unlabeled')"


def _american_implied_prob(odds: int | None) -> float:
    if odds is None:
        return 0.0
    if odds > 0:
        return round(100 / (odds + 100), 4)
    return round((-odds) / ((-odds) + 100), 4)


async def _odds_snapshot_query() -> tuple[str, str]:
    columns = await get_table_columns("odds_history")
    if not columns:
        raise HTTPException(404, "No odds snapshot source available.")
    date_expr = ODDS_HISTORY_DATE_EXPR if "event_date" in columns else "CURRENT_DATE"
    query = f"""
        WITH latest AS (
            SELECT DISTINCT ON (player, market, book, side, line)
                   event_id,
                   {date_expr} AS snapshot_date,
                   pulled_at,
                   home_team,
                   away_team,
                   book,
                   market,
                   player,
                   side,
                   line,
                   odds
            FROM odds_history
            WHERE {date_expr} = CURRENT_DATE
            ORDER BY player, market, book, side, line, pulled_at DESC
        )
        SELECT *
        FROM latest
        ORDER BY away_team, home_team, market, player, book
    """
    return query, "odds_history"


async def _fallback_odds_snapshot_query() -> tuple[str, str]:
    player_columns = await get_table_columns("player_odds")
    saves_columns = await get_table_columns("saves_odds")
    if not player_columns and not saves_columns:
        raise HTTPException(404, "No odds tables available.")

    sources: list[str] = []
    if player_columns:
        sources.append(
            """
            SELECT
                event_id,
                event_date::date AS snapshot_date,
                COALESCE(NULLIF(updated_at, '')::timestamp, NULLIF(scraped_at, '')::timestamp, NOW()) AS pulled_at,
                home_team,
                away_team,
                book_name AS book,
                market,
                player_name AS player,
                'over' AS side,
                line,
                over_odds AS odds
            FROM player_odds
            WHERE event_date::date = COALESCE(
                (SELECT MAX(event_date::date) FROM player_odds WHERE event_date::date = CURRENT_DATE),
                (SELECT MAX(event_date::date) FROM player_odds)
            )

            UNION ALL

            SELECT
                event_id,
                event_date::date AS snapshot_date,
                COALESCE(updated_at::timestamp, scraped_at::timestamp, NOW()) AS pulled_at,
                home_team,
                away_team,
                book_name AS book,
                market,
                player_name AS player,
                'under' AS side,
                line,
                under_odds AS odds
            FROM player_odds
            WHERE event_date::date = COALESCE(
                (SELECT MAX(event_date::date) FROM player_odds WHERE event_date::date = CURRENT_DATE),
                (SELECT MAX(event_date::date) FROM player_odds)
            )
            """
        )
    if saves_columns:
        sources.append(
            """
            SELECT
                event_id,
                event_date::date AS snapshot_date,
                COALESCE(NULLIF(updated_at, '')::timestamp, scraped_at::timestamp, NOW()) AS pulled_at,
                home_team,
                away_team,
                book_name AS book,
                'saves' AS market,
                player_name AS player,
                'over' AS side,
                line,
                over_odds AS odds
            FROM saves_odds
            WHERE event_date::date = COALESCE(
                (SELECT MAX(event_date::date) FROM saves_odds WHERE event_date::date = CURRENT_DATE),
                (SELECT MAX(event_date::date) FROM saves_odds)
            )

            UNION ALL

            SELECT
                event_id,
                event_date::date AS snapshot_date,
                COALESCE(updated_at::timestamp, scraped_at::timestamp, NOW()) AS pulled_at,
                home_team,
                away_team,
                book_name AS book,
                'saves' AS market,
                player_name AS player,
                'under' AS side,
                line,
                under_odds AS odds
            FROM saves_odds
            WHERE event_date::date = COALESCE(
                (SELECT MAX(event_date::date) FROM saves_odds WHERE event_date::date = CURRENT_DATE),
                (SELECT MAX(event_date::date) FROM saves_odds)
            )
            """
        )

    query = f"""
        WITH source_rows AS (
            {' UNION ALL '.join(sources)}
        ),
        latest AS (
            SELECT DISTINCT ON (player, market, book, side, line)
                   event_id,
                   snapshot_date,
                   pulled_at,
                   home_team,
                   away_team,
                   book,
                   market,
                   player,
                   side,
                   line,
                   odds
            FROM source_rows
            ORDER BY player, market, book, side, line, pulled_at DESC
        )
        SELECT *
        FROM latest
        ORDER BY away_team, home_team, market, player, book
    """
    return query, "player_odds/saves_odds"


@router.get("/model/info")
async def get_model_info():
    return await asyncio.to_thread(_load_model_info_sync)


@router.get("/picks/today")
async def get_today_picks():
    pool = get_pool("nhl_picks")
    strategy_expr = await _pick_strategy_expr()
    rows = await pool.fetch(
        f"""
        SELECT
            pick_id,
            pick_date,
            player,
            market,
            bet,
            line,
            odds,
            book,
            edge,
            model_prediction,
            units,
            dollars,
            confidence,
            {strategy_expr} AS strategy,
            result,
            pnl
        FROM nhl_picks
        WHERE pick_date = CURRENT_DATE
        ORDER BY edge DESC NULLS LAST, player
        """
    )

    picks = [
        {
            "pick_id": row["pick_id"],
            "pick_date": row["pick_date"].isoformat() if row["pick_date"] else None,
            "player": row["player"],
            "market": row["market"],
            "side": row["bet"],
            "line": _num(row["line"]),
            "odds": int(row["odds"]) if row["odds"] is not None else None,
            "book": row["book"],
            "edge": _num(row["edge"]),
            "edge_pct": round(_num(row["edge"]) * 100, 2),
            "model_prob": _num(row["model_prediction"]),
            "model_prob_pct": round(_num(row["model_prediction"]) * 100, 2),
            "implied_prob": _american_implied_prob(row["odds"]),
            "implied_prob_pct": round(_american_implied_prob(row["odds"]) * 100, 2),
            "stake": _num(row["units"]),
            "stake_dollars": _num(row["dollars"]),
            "strategy": row["strategy"],
            "confidence": row["confidence"],
            "result": row["result"],
            "pnl": _num(row["pnl"]),
        }
        for row in rows
    ]
    return {
        "pick_date": date.today().isoformat(),
        "count": len(picks),
        "total_stake": round(sum(item["stake"] for item in picks), 2),
        "total_stake_dollars": round(sum(item["stake_dollars"] for item in picks), 2),
        "picks": picks,
    }


@router.get("/picks/history")
async def get_pick_history(
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    strategy: str | None = None,
):
    pool = get_pool("nhl_picks")
    strategy_expr = await _pick_strategy_expr()
    params: list[Any] = [days]
    filters = ["pick_date >= CURRENT_DATE - ($1::int * INTERVAL '1 day')"]
    if strategy:
        params.append(strategy)
        filters.append(f"{strategy_expr} = $2")

    rows = await pool.fetch(
        f"""
        SELECT
            pick_id,
            pick_date,
            player,
            market,
            bet,
            line,
            odds,
            book,
            edge,
            model_prediction,
            units,
            dollars,
            confidence,
            {strategy_expr} AS strategy,
            result,
            pnl,
            graded_at
        FROM nhl_picks
        WHERE {' AND '.join(filters)}
        ORDER BY pick_date DESC, edge DESC NULLS LAST, player
        """,
        *params,
    )
    strategies = await pool.fetch(
        f"""
        SELECT DISTINCT {strategy_expr} AS strategy
        FROM nhl_picks
        WHERE pick_date >= CURRENT_DATE - ($1::int * INTERVAL '1 day')
        ORDER BY strategy
        """,
        days,
    )

    picks = []
    wins = losses = pushes = pending = 0
    total_pl = total_staked = 0.0
    for row in rows:
        result = (row["result"] or "Pending").strip() if row["result"] else "Pending"
        if result == "W":
            wins += 1
        elif result == "L":
            losses += 1
        elif result == "P":
            pushes += 1
        else:
            pending += 1
        total_pl += float(row["pnl"] or 0)
        total_staked += float(row["dollars"] or 0)
        picks.append(
            {
                "pick_id": row["pick_id"],
                "pick_date": row["pick_date"].isoformat() if row["pick_date"] else None,
                "player": row["player"],
                "market": row["market"],
                "side": row["bet"],
                "line": _num(row["line"]),
                "odds": int(row["odds"]) if row["odds"] is not None else None,
                "book": row["book"],
                "edge": _num(row["edge"]),
                "edge_pct": round(_num(row["edge"]) * 100, 2),
                "model_prob": _num(row["model_prediction"]),
                "model_prob_pct": round(_num(row["model_prediction"]) * 100, 2),
                "stake": _num(row["units"]),
                "stake_dollars": _num(row["dollars"]),
                "strategy": row["strategy"],
                "confidence": row["confidence"],
                "result": result,
                "pnl": _num(row["pnl"]),
                "graded_at": row["graded_at"].isoformat() if row["graded_at"] else None,
            }
        )

    return {
        "days": days,
        "strategy": strategy,
        "summary": {
            "wins": wins,
            "losses": losses,
            "pushes": pushes,
            "pending": pending,
            "record": f"{wins}-{losses}-{pushes}",
            "total_pl": round(total_pl, 2),
            "total_staked": round(total_staked, 2),
            "roi": round((total_pl / total_staked) * 100, 2) if total_staked else 0.0,
        },
        "strategies": [row["strategy"] for row in strategies if row["strategy"]],
        "picks": picks,
    }


@router.get("/odds/snapshot")
async def get_odds_snapshot():
    pool = get_pool()
    columns = await get_table_columns("odds_history")
    if columns:
        query, source = await _odds_snapshot_query()
    else:
        query, source = await _fallback_odds_snapshot_query()

    rows = await pool.fetch(query)
    games: dict[str, dict[str, Any]] = {}
    for row in rows:
        game_key = f'{row["away_team"]} @ {row["home_team"]}'
        market_key = f'{row["player"]}:{row["market"]}'
        game = games.setdefault(
            game_key,
            {
                "game": game_key,
                "away_team": row["away_team"],
                "home_team": row["home_team"],
                "event_id": row["event_id"],
                "snapshot_date": row["snapshot_date"].isoformat() if row["snapshot_date"] else None,
                "markets": {},
            },
        )
        market = game["markets"].setdefault(
            market_key,
            {
                "player": row["player"],
                "market": row["market"],
                "offers": [],
                "best_over_odds": None,
                "best_under_odds": None,
            },
        )
        odds = int(row["odds"]) if row["odds"] is not None else None
        offer = {
            "book": row["book"],
            "side": row["side"],
            "line": _num(row["line"]),
            "odds": odds,
            "pulled_at": row["pulled_at"].isoformat() if row["pulled_at"] else None,
        }
        market["offers"].append(offer)
        if row["side"] == "over":
            current = market["best_over_odds"]
            if current is None or (odds is not None and odds > current["odds"]):
                market["best_over_odds"] = offer
        elif row["side"] == "under":
            current = market["best_under_odds"]
            if current is None or (odds is not None and odds > current["odds"]):
                market["best_under_odds"] = offer

    grouped_games = []
    for game in games.values():
        grouped_games.append(
            {
                **game,
                "markets": sorted(game["markets"].values(), key=lambda item: (item["market"], item["player"])),
            }
        )
    grouped_games.sort(key=lambda item: item["game"])

    return {
        "source": source,
        "snapshot_date": grouped_games[0]["snapshot_date"] if grouped_games else None,
        "games": grouped_games,
    }


@router.get("/model/strategies")
async def get_model_strategies(days: Annotated[int, Query(ge=1, le=365)] = 30):
    pool = get_pool("nhl_picks")
    strategy_expr = await _pick_strategy_expr()
    rows = await pool.fetch(
        f"""
        SELECT
            {strategy_expr} AS strategy,
            COUNT(*) AS pick_count,
            COUNT(*) FILTER (WHERE result = 'W') AS wins,
            COUNT(*) FILTER (WHERE result = 'L') AS losses,
            COUNT(*) FILTER (WHERE result = 'P') AS pushes,
            COUNT(*) FILTER (WHERE result IS NULL OR result NOT IN ('W', 'L', 'P')) AS pending,
            COALESCE(SUM(pnl), 0) AS total_pl,
            COALESCE(SUM(dollars), 0) AS total_staked,
            COALESCE(AVG(edge), 0) AS avg_edge
        FROM nhl_picks
        WHERE pick_date >= CURRENT_DATE - ($1::int * INTERVAL '1 day')
        GROUP BY 1
        ORDER BY total_pl DESC, avg_edge DESC
        """,
        days,
    )
    return {
        "days": days,
        "strategies": [
            {
                "strategy": row["strategy"],
                "pick_count": int(row["pick_count"] or 0),
                "wins": int(row["wins"] or 0),
                "losses": int(row["losses"] or 0),
                "pushes": int(row["pushes"] or 0),
                "pending": int(row["pending"] or 0),
                "record": f'{int(row["wins"] or 0)}-{int(row["losses"] or 0)}-{int(row["pushes"] or 0)}',
                "roi": (
                    round((float(row["total_pl"] or 0) / float(row["total_staked"] or 0)) * 100, 2)
                    if float(row["total_staked"] or 0)
                    else 0.0
                ),
                "avg_edge": round(float(row["avg_edge"] or 0) * 100, 2),
                "total_pl": round(float(row["total_pl"] or 0), 2),
                "total_staked": round(float(row["total_staked"] or 0), 2),
            }
            for row in rows
        ],
    }
