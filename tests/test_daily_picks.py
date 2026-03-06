"""Regression tests for daily pick sizing helpers."""

from model.bankroll import kelly_size
from models.player_points import calc_edge
from pipeline.daily_picks import apply_max_risk_cap, sort_picks_by_edge


class TestDailyPicks:
    def test_edge_calculation_uses_model_prob_minus_implied_prob(self):
        edge, breakeven = calc_edge(0.61, -120)

        assert round(breakeven, 4) == 0.5455, "Breakeven probability should reflect the market price."
        assert round(edge, 4) == 0.0645, "Edge should equal model probability minus implied probability."

    def test_kelly_criterion_sizing_returns_positive_units_and_dollars(self):
        units, dollars = kelly_size(win_prob=0.60, odds=-110, bankroll=1000)

        assert units > 0, "Positive edge bets should receive a positive Kelly unit size."
        assert dollars > 0, "Positive edge bets should receive a positive dollar stake."

    def test_max_risk_cap_scales_total_deployment(self):
        picks = [
            {"player": "A", "edge": 0.12, "units": 4.0, "dollars": 80.0},
            {"player": "B", "edge": 0.08, "units": 3.0, "dollars": 60.0},
        ]

        scaled, total_risk, scale = apply_max_risk_cap(picks, 100)

        assert round(total_risk, 2) == 100.0, "Scaled picks should not exceed the configured max risk cap."
        assert round(scale, 4) == round(100 / 140, 4), "Scaling factor should reflect capped risk over raw risk."
        assert scaled[0]["dollars"] < 80.0, "Each pick should be scaled down proportionally when risk is capped."

    def test_picks_are_sorted_by_edge_descending(self):
        picks = [
            {"player": "B", "edge": 0.04},
            {"player": "A", "edge": 0.11},
            {"player": "C", "edge": 0.07},
        ]

        sorted_picks = sort_picks_by_edge(picks)

        assert [pick["player"] for pick in sorted_picks] == ["A", "C", "B"], (
            "Daily picks should be ordered from highest edge to lowest edge."
        )
