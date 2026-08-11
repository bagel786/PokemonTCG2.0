import json

import pytest

from training.evaluation_schema import EvaluationSchemaError
from training.promotion import aggregate_shards, evaluate_probe_gate


def result(wins=6000, games=10000, *, seed=1, model="candidate", errors=0, bundle="bundle"):
    half = games // 2
    seat0_wins = wins // 2
    seat1_wins = wins - seat0_wins
    return {
        "games": games,
        "wins_a": wins,
        "win_rate_a": wins / games,
        "wilson_95": [0.0, 1.0],
        "overall": {"games": games, "wins": wins, "win_rate": wins / games, "wilson_95": [0.0, 1.0]},
        "hero_policy_errors": errors,
        "opponent_policy_errors": 0,
        "elapsed_seconds": 1.0,
        "decisions": games * 10,
        "seat_results_a": {
            "0": {"games": half, "wins": seat0_wins, "win_rate": seat0_wins / half},
            "1": {"games": games - half, "wins": seat1_wins, "win_rate": seat1_wins / (games - half)},
        },
        "opponent_results_a": {"control": {"games": games, "wins": wins, "win_rate": wins / games, "wilson_95": [0.0, 1.0]}},
        "rng_provenance": {"engine": "unpaired_std_random_device", "paired_deals": False},
        "artifact_provenance": {
            "source_commit": "abc",
            "source_bundle_sha256": bundle,
            "worker": f"worker-{seed}",
            "seed": seed,
            "deck_a_sha256": "deck-a",
            "model_a_sha256": model,
            "deck_b_sha256": "deck-b",
            "model_b_sha256": "control",
            "engine_binary": "libcg.so",
            "engine_sha256": "engine",
            "runtime_environment": {
                "process_ptcg": {},
                "submission_a_overrides": {},
                "submission_b_overrides": {},
            },
            "artifact_a_sha256": model,
            "artifact_b_sha256": "control",
            "artifact_a_schema": 2,
            "artifact_b_schema": 2,
        },
    }


def write(tmp_path, name, payload):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def test_aggregation_rejects_hash_mismatch(tmp_path):
    first = write(tmp_path, "a.json", result(seed=1))
    second_row = result(seed=2, model="different")
    second = write(tmp_path, "b.json", second_row)
    with pytest.raises(EvaluationSchemaError):
        aggregate_shards([first, second])


def test_aggregation_rejects_source_bundle_mismatch_and_duplicate_seed(tmp_path):
    first = write(tmp_path, "a.json", result(seed=1))
    different_bundle = write(tmp_path, "b.json", result(seed=2, bundle="different"))
    with pytest.raises(EvaluationSchemaError):
        aggregate_shards([first, different_bundle])
    duplicate_seed = write(tmp_path, "c.json", result(seed=1))
    with pytest.raises(EvaluationSchemaError):
        aggregate_shards([first, duplicate_seed])


def test_probe_requires_three_full_shards_and_authentic_baseline(tmp_path):
    candidate_paths = [write(tmp_path, f"c{i}.json", result(seed=i)) for i in range(3)]
    control_paths = [write(tmp_path, f"b{i}.json", result(seed=i + 4, model="baseline")) for i in range(3)]
    candidate = aggregate_shards(candidate_paths)
    control = aggregate_shards(control_paths)
    decision = evaluate_probe_gate(candidate, control)
    assert decision["passed"] is False
    assert decision["checks"]["authentic_regression_no_worse_than_2_points"] is False


def test_policy_errors_cannot_pass_probe(tmp_path):
    candidate_paths = [write(tmp_path, f"c{i}.json", result(seed=i, errors=1)) for i in range(3)]
    control_paths = [write(tmp_path, f"b{i}.json", result(seed=i + 4, model="baseline")) for i in range(3)]
    candidate = aggregate_shards(candidate_paths)
    control = aggregate_shards(control_paths)
    decision = evaluate_probe_gate(candidate, control, {"auth": (candidate, control)})
    assert decision["checks"]["zero_policy_errors"] is False
    assert decision["passed"] is False
