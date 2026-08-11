import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from training.evaluation_schema import (
    EvaluationSchemaError,
    build_provenance,
    sha256_path,
    validate_evaluation_result,
)


def valid_result():
    return {
        "games": 10,
        "wins_a": 6,
        "win_rate_a": 0.6,
        "wilson_95": [0.3, 0.8],
        "overall": {"games": 10, "wins": 6, "win_rate": 0.6, "wilson_95": [0.3, 0.8]},
        "hero_policy_errors": 0,
        "opponent_policy_errors": 0,
        "elapsed_seconds": 1.0,
        "decisions": 100,
        "seat_results_a": {
            "0": {"games": 5, "wins": 4, "win_rate": 0.8},
            "1": {"games": 5, "wins": 2, "win_rate": 0.4},
        },
        "opponent_results_a": {"d842": {"games": 10, "wins": 6, "win_rate": 0.6, "wilson_95": [0.3, 0.8]}},
        "rng_provenance": {"engine": "unpaired_std_random_device", "paired_deals": False},
        "artifact_provenance": {
            "source_commit": "abc123",
            "source_bundle_sha256": "bundle",
            "worker": "worker-1",
            "seed": 7,
            "deck_a_sha256": "a",
            "deck_b_sha256": "b",
            "engine_binary": "cg.dll",
            "engine_sha256": "c",
            "runtime_environment": {
                "process_ptcg": {},
                "submission_a_overrides": {},
                "submission_b_overrides": {},
            },
            "artifact_a_sha256": "model-a",
            "artifact_b_sha256": "model-b",
            "artifact_a_schema": 2,
            "artifact_b_schema": 2,
        },
    }


class EvaluationSchemaTests(unittest.TestCase):
    def test_artifact_tree_hash_ignores_python_cache_files(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "main.py").write_text("pass\n")
            before = sha256_path(root)
            cache = root / "__pycache__"
            cache.mkdir()
            (cache / "main.pyc").write_bytes(b"runtime cache")
            self.assertEqual(sha256_path(root), before)

    def test_accepts_complete_consistent_result(self):
        self.assertEqual(validate_evaluation_result(valid_result())["wins_a"], 6)

    def test_provenance_hashes_selected_engine_and_records_runtime_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deck_a = root / "a.csv"
            deck_b = root / "b.csv"
            engine = root / "cg.dll"
            deck_a.write_text("1\n", encoding="utf-8")
            deck_b.write_text("2\n", encoding="utf-8")
            engine.write_bytes(b"windows engine")
            environment = {
                "PTCG_SEARCH": "0",
                "PTCG_TEMP": "1.5",
                "PTCG_SOURCE_COMMIT": "test-commit",
            }
            with patch.dict(os.environ, environment, clear=True):
                provenance = build_provenance(
                    root=root,
                    deck_a=deck_a,
                    model_a=None,
                    deck_b=deck_b,
                    model_b=None,
                    submission_a=None,
                    submission_b=None,
                    engine_path=engine,
                    seed=7,
                    submission_env_a={"PTCG_TACTICAL_SHIELD": "1"},
                    submission_env_b={"NO_SEARCH": "1"},
                )
            self.assertEqual(provenance["engine_binary"], "cg.dll")
            self.assertEqual(provenance["engine_sha256"], hashlib.sha256(b"windows engine").hexdigest())
            self.assertEqual(
                provenance["runtime_environment"],
                {
                    "process_ptcg": {"PTCG_SEARCH": "0", "PTCG_TEMP": "1.5"},
                    "submission_a_overrides": {"PTCG_TACTICAL_SHIELD": "1"},
                    "submission_b_overrides": {"NO_SEARCH": "1"},
                },
            )

    def test_missing_seat_metrics_fail_closed(self):
        result = valid_result()
        del result["seat_results_a"]
        with self.assertRaises(EvaluationSchemaError):
            validate_evaluation_result(result)

    def test_missing_errors_fail_closed(self):
        result = valid_result()
        del result["hero_policy_errors"]
        with self.assertRaises(EvaluationSchemaError):
            validate_evaluation_result(result)

    def test_inconsistent_counts_fail_closed(self):
        result = copy.deepcopy(valid_result())
        result["seat_results_a"]["1"]["wins"] = 3
        with self.assertRaises(EvaluationSchemaError):
            validate_evaluation_result(result)

    def test_unknown_commit_fails_closed(self):
        result = valid_result()
        result["artifact_provenance"]["source_commit"] = "unknown"
        with self.assertRaises(EvaluationSchemaError):
            validate_evaluation_result(result)

    def test_missing_runtime_environment_fails_closed(self):
        result = valid_result()
        del result["artifact_provenance"]["runtime_environment"]
        with self.assertRaises(EvaluationSchemaError):
            validate_evaluation_result(result)


if __name__ == "__main__":
    unittest.main()
