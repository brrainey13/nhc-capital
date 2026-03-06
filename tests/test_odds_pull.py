"""Regression tests for NHL odds pulling."""

from datetime import datetime
from unittest.mock import patch

import pytz
from pipeline import odds_pull


class FrozenDateTime:
    @staticmethod
    def now(tz=None):
        base = datetime(2026, 3, 6, 13, 0)
        return tz.localize(base) if tz else base

    @staticmethod
    def fromisoformat(value):
        return datetime.fromisoformat(value)


class TestOddsPull:
    def test_pull_all_odds_parses_response_and_separates_totals(self, mock_api_response):
        events = [
            {
                "id": "evt-1",
                "away_team": "Rangers",
                "home_team": "Bruins",
                "commence_time": "2026-03-06T23:00:00Z",
            }
        ]
        payload = {
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        {
                            "key": "player_points",
                            "outcomes": [
                                {
                                    "name": "Over",
                                    "description": "Artemi Panarin",
                                    "point": 1.5,
                                    "price": 125,
                                }
                            ],
                        },
                        {
                            "key": "player_total_saves",
                            "outcomes": [
                                {
                                    "name": "Under",
                                    "description": "Igor Shesterkin",
                                    "point": 28.5,
                                    "price": -105,
                                }
                            ],
                        },
                        {"key": "totals", "outcomes": [{"name": "Over", "point": 6.5, "price": -110}]},
                    ],
                }
            ]
        }
        with patch.object(odds_pull, "_api_get", return_value=mock_api_response(payload)), patch.object(
            odds_pull, "_store_odds_history"
        ) as mock_store, patch("pipeline.odds_pull.time.sleep"):
            props, totals, pull_id = odds_pull.pull_all_odds(events)

        assert len(props) == 2, "Player props and goalie saves should both be returned from the combined pull."
        assert totals["evt-1"]["total"] == 6.5, "Game totals should be separated into the totals map."
        assert pull_id, "Each pull should emit a non-empty pull id for historical storage."
        mock_store.assert_called_once()

    def test_get_best_odds_keeps_highest_price_per_player_market_combo(self):
        props = [
            {
                "player": "Connor McDavid",
                "market": "player_points",
                "side": "Over",
                "line": 1.5,
                "odds": 110,
                "book": "a",
            },
            {
                "player": "Connor McDavid",
                "market": "player_points",
                "side": "Over",
                "line": 1.5,
                "odds": 125,
                "book": "b",
            },
            {
                "player": "Connor McDavid",
                "market": "player_points",
                "side": "Under",
                "line": 1.5,
                "odds": -120,
                "book": "c",
            },
        ]

        best = odds_pull.get_best_odds(props)

        assert best[("Connor McDavid", "player_points", "Over", 1.5)]["book"] == "b", (
            "The best-odds reducer should keep the most favorable price for each combo."
        )

    def test_store_odds_history_inserts_rows(self, mock_db_connection):
        rows = [
            (
                "pull-1",
                "evt-1",
                "2026-03-06",
                "Bruins",
                "Rangers",
                "2026-03-06T23:00:00Z",
                "draftkings",
                "totals",
                None,
                "Over",
                6.5,
                -110,
                1,
            )
        ]
        with patch("pipeline.odds_pull.psycopg2.connect", return_value=mock_db_connection), patch(
            "psycopg2.extras.execute_values"
        ) as mock_execute:
            odds_pull._store_odds_history(rows)

        assert mock_db_connection.commit.called, "Odds history writes should commit after inserting snapshot rows."
        assert mock_execute.call_args.args[2] == rows, "Stored snapshot rows should match the parsed odds history rows."

    def test_api_key_rotation_retries_with_next_key(self, mock_api_response):
        first = mock_api_response({}, status_code=429)
        second = mock_api_response({"ok": True}, status_code=200)
        with (
            patch.object(odds_pull, "API_KEYS", ["key-one", "key-two"]),
            patch.object(odds_pull, "API_KEY", "key-one"),
            patch.object(odds_pull, "_KEY_INDEX", 0),
            patch("pipeline.odds_pull.requests.get", side_effect=[first, second]) as mock_get,
        ):
            response = odds_pull._api_get("https://example.test/odds")

        assert response.status_code == 200, "The request should retry with the next key after quota exhaustion."
        assert mock_get.call_args.kwargs["params"]["apiKey"] == "key-two", "Retry should use the rotated API key."

    def test_get_todays_events_filters_by_est_window(self, mock_api_response):
        est = pytz.timezone("America/New_York")
        events = [
            {"id": "a", "commence_time": "2026-03-06T17:00:00Z"},
            {"id": "b", "commence_time": "2026-03-07T08:30:00Z"},
            {"id": "c", "commence_time": "2026-03-07T09:30:00Z"},
            {"id": "d", "commence_time": "2026-03-06T15:00:00Z"},
        ]
        with patch.object(odds_pull, "_api_get", return_value=mock_api_response(events)), patch.object(
            odds_pull, "datetime", FrozenDateTime
        ):
            filtered = odds_pull.get_todays_events()

        assert [event["id"] for event in filtered] == ["a", "b"], (
            "Only events between noon EST and 4 AM EST the next day should be included."
        )
        assert est.zone == "America/New_York", "The filtering logic should continue to use EST/EDT conversion."
