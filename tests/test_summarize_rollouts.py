import gzip
import json
import sys

from scripts.summarize_rollouts import main


def test_rollout_summary_checks_trajectory_integrity(tmp_path, monkeypatch):
    path = tmp_path / "rollouts.jsonl.gz"
    rows = [
        {
            "trajectory_id": "game-0",
            "decision_index": 0,
            "action": [2, 0],
            "selection_order": [2, 0],
            "old_logprob": -1.25,
            "trainable": True,
            "opponent": "mirror",
            "return": 1.0,
            "policy_version": "abc123",
            "model_schema_version": 2,
        },
        {
            "trajectory_id": "game-0",
            "decision_index": 1,
            "action": [1],
            "selection_order": [1],
            "old_logprob": -0.5,
            "trainable": False,
            "opponent": "mirror",
            "return": 1.0,
            "policy_version": "abc123",
            "model_schema_version": 2,
        },
    ]
    with gzip.open(path, "wt") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    output = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["summarize_rollouts.py", str(path), "--output", str(output)])

    assert main() == 0
    summary = json.loads(output.read_text())
    assert summary["games"] == 1
    assert summary["decisions"] == 2
    assert summary["trainable_decisions"] == 1
    assert summary["wins"] == 1
    assert summary["decision_index_errors"] == 0
    assert summary["selection_order_mismatches"] == 0
    assert summary["invalid_logprobs"] == 0
