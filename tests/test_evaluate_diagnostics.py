import unittest
from types import SimpleNamespace
from unittest.mock import patch

from training.evaluate import capture_initial_first_player, external_diagnostics
from training.seat_adjusted import newcombe_difference, structural_lift


class EvaluateDiagnosticsTests(unittest.TestCase):
    def test_external_numeric_diagnostics_exclude_strings_and_bools(self):
        fake = SimpleNamespace(
            module=SimpleNamespace(
                RUNTIME_STATS={"search_exception": 2, "last_error": "boom", "flag": True},
                search=SimpleNamespace(STATS={"calls": 7, "search_s_total": 1.25, "last_err": ""}),
            )
        )
        with patch("training.evaluate.ExternalSubmissionAgent", new=type(fake)):
            runtime, search = external_diagnostics(fake)
        self.assertEqual(runtime, {"search_exception": 2.0})
        self.assertEqual(search, {"calls": 7.0, "search_s_total": 1.25})

    def test_non_external_agent_has_no_external_diagnostics(self):
        self.assertEqual(external_diagnostics(object()), ({}, {}))

    def test_first_player_is_captured_from_opening_and_not_terminal_state(self):
        opening = SimpleNamespace(firstPlayer=1)
        terminal = SimpleNamespace(firstPlayer=-1)
        captured = capture_initial_first_player(opening)
        self.assertEqual(captured, 1)
        self.assertEqual(capture_initial_first_player(terminal, captured), 1)

    def test_newcombe_interval_and_relative_seat_gate(self):
        control = {
            "wilson_95": [0.49, 0.51],
            "seat_results_a": {
                "0": {"games": 50000, "wins": 26500, "win_rate": 0.53},
                "1": {"games": 50000, "wins": 23500, "win_rate": 0.47},
            },
            "first_player_results_a": {
                "first": {"games": 50000, "wins": 26000, "win_rate": 0.52},
                "second": {"games": 50000, "wins": 24000, "win_rate": 0.48},
            },
        }
        challenger = {
            "wilson_95": [0.501, 0.521],
            "hero_policy_errors": 0,
            "opponent_policy_errors": 0,
            "seat_results_a": {
                "0": {"games": 50000, "wins": 27000, "win_rate": 0.54},
                "1": {"games": 50000, "wins": 24000, "win_rate": 0.48},
            },
            "first_player_results_a": {
                "first": {"games": 50000, "wins": 26500, "win_rate": 0.53},
                "second": {"games": 50000, "wins": 24500, "win_rate": 0.49},
            },
        }
        self.assertTrue(structural_lift(control, challenger)["passed"])
        lower, upper = newcombe_difference(27000, 50000, 26500, 50000)
        self.assertLess(lower, 0.01)
        self.assertGreater(upper, 0.01)


if __name__ == "__main__":
    unittest.main()
