"""Regression tests for goalie strategy live feature building."""

from unittest.mock import patch

from model import goalie_strategy


class FakeCursor:
    def __init__(self, fetchall_values=None, fetchone_values=None):
        self.fetchall_values = list(fetchall_values or [])
        self.fetchone_values = list(fetchone_values or [])
        self.executions = []

    def execute(self, query, params=None):
        self.executions.append((query, params))

    def fetchall(self):
        return self.fetchall_values.pop(0)

    def fetchone(self):
        return self.fetchone_values.pop(0)


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def _feature_cursor():
    return FakeCursor(
        fetchall_values=[
            [(1, "Boston Bruins", "BOS"), (2, "New York Rangers", "NYR")],
            [
                (31, 32, 0.93, "2026-02-25", 0),
                (29, 30, 0.90, "2026-02-27", 0),
                (30, 31, 0.91, "2026-03-01", 1),
                (34, 35, 0.94, "2026-03-03", 0),
                (28, 29, 0.90, "2026-03-05", 0),
            ],
            [
                (101, 56, 31, 8, 4, 3),
                (102, 54, 30, 6, 5, 2),
                (103, 50, 28, 5, 4, 4),
            ],
            [
                (201, 62, 35, 7, 3, 4, "2026-03-04"),
                (202, 60, 33, 8, 2, 3, "2026-03-02"),
                (203, 58, 34, 6, 2, 2, "2026-02-28"),
            ],
        ],
        fetchone_values=[
            (30, "Igor Shesterkin", 2),
            (47,),
            (45,),
            (44,),
            (51,),
            (50,),
            (49,),
        ],
    )


class TestGoalieStrategy:
    def test_fetch_team_context_returns_expected_structure(self):
        cursor = FakeCursor(
            fetchall_values=[
                [
                    (201, 62, 35, 7, 3, 4, "2026-03-04"),
                    (202, 60, 33, 8, 2, 3, "2026-03-02"),
                    (203, 58, 34, 6, 2, 2, "2026-02-28"),
                ]
            ],
            fetchone_values=[(51,), (50,), (49,)],
        )

        context = goalie_strategy._fetch_team_context(cursor, 1, "2026-03-06")

        assert set(context) == {
            "opp_team_sog_avg_10",
            "opp_team_pp_opps_avg_10",
            "opp_puck_control_avg_10",
            "opp_corsi_pct_avg_10",
            "opp_corsi_diff_avg_10",
        }, "Team context should expose the features required by the live goalie strategy."

    def test_target_date_is_sent_to_sql_as_string(self):
        cursor = _feature_cursor()
        connection = FakeConnection(cursor)
        events = [{"id": "evt-1", "home_team": "Boston Bruins", "away_team": "New York Rangers"}]
        props = [
            {
                "player": "Igor Shesterkin",
                "market": "player_total_saves",
                "side": "Over",
                "line": 28.5,
                "odds": -110,
                "event_id": "evt-1",
                "book": "dk",
                "book_title": "DraftKings",
            }
        ]
        best = {("Igor Shesterkin", "player_total_saves", "Over", 28.5): props[0]}

        with patch.object(goalie_strategy, "_get_conn", return_value=connection), patch(
            "pipeline.odds_pull.pull_player_props", return_value=props
        ), patch("pipeline.odds_pull.get_best_odds", return_value=best):
            goalie_strategy._build_live_goalie_features(events, "2026-03-06")

        dated_params = [params for query, params in cursor.executions if params and "g.game_date < %s" in query]
        assert dated_params, "The live feature builder should issue dated SQL queries."
        assert all(isinstance(params[1], str) for params in dated_params), (
            "SQL comparisons against game_date should receive strings, not datetime.date objects."
        )

    def test_build_live_goalie_features_returns_complete_row(self):
        cursor = _feature_cursor()
        connection = FakeConnection(cursor)
        events = [{"id": "evt-1", "home_team": "Boston Bruins", "away_team": "New York Rangers"}]
        over = {
            "player": "Igor Shesterkin",
            "market": "player_total_saves",
            "side": "Over",
            "line": 28.5,
            "odds": -110,
            "event_id": "evt-1",
            "book": "dk",
            "book_title": "DraftKings",
        }
        under = {
            "player": "Igor Shesterkin",
            "market": "player_total_saves",
            "side": "Under",
            "line": 28.5,
            "odds": -105,
            "event_id": "evt-1",
            "book": "fd",
            "book_title": "FanDuel",
        }
        best = {
            ("Igor Shesterkin", "player_total_saves", "Over", 28.5): over,
            ("Igor Shesterkin", "player_total_saves", "Under", 28.5): under,
        }

        with patch.object(goalie_strategy, "_get_conn", return_value=connection), patch(
            "pipeline.odds_pull.pull_player_props", return_value=[over, under]
        ), patch("pipeline.odds_pull.get_best_odds", return_value=best):
            rows = goalie_strategy._build_live_goalie_features(events, "2026-03-06")

        assert len(rows) == 1, "A fully matched goalie with enough history should yield one feature row."
        assert {
            "player",
            "player_team",
            "game",
            "line",
            "sa_avg_10",
            "opp_team_sog_avg_10",
            "over_offer",
            "under_offer",
        } <= rows[0].keys(), (
            "Each live goalie row should include the core model features plus both market offers."
        )

    def test_feature_dict_has_all_required_keys(self):
        cursor = _feature_cursor()
        connection = FakeConnection(cursor)
        events = [{"id": "evt-1", "home_team": "Boston Bruins", "away_team": "New York Rangers"}]
        offer = {
            "player": "Igor Shesterkin",
            "market": "player_total_saves",
            "side": "Over",
            "line": 28.5,
            "odds": -110,
            "event_id": "evt-1",
            "book": "dk",
            "book_title": "DraftKings",
        }
        best = {("Igor Shesterkin", "player_total_saves", "Over", 28.5): offer}

        with patch.object(goalie_strategy, "_get_conn", return_value=connection), patch(
            "pipeline.odds_pull.pull_player_props", return_value=[offer]
        ), patch("pipeline.odds_pull.get_best_odds", return_value=best):
            row = goalie_strategy._build_live_goalie_features(events, "2026-03-06")[0]

        missing = [feature for feature in goalie_strategy.GOALIE_STRATEGY_FEATURES if feature not in row]
        assert not missing, "Live goalie rows should expose every feature expected by the strategy model."
