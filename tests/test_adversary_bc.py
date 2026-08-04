import gzip
import json

from training.train_adversary_bc import candidate_specifications, fidelity_gate, split_counts


def test_candidate_specifications_include_three_fresh_and_initialized_seeds():
    specifications = candidate_specifications(11, "base.npz")
    assert [row["name"] for row in specifications] == [
        "fresh_seed11", "fresh_seed12", "fresh_seed13",
        "initialized_seed11", "initialized_seed12", "initialized_seed13",
    ]
    assert sum(row["initial_model"] is None for row in specifications) == 3


def test_fidelity_gate_is_only_a_minimum_integrity_filter():
    reports = {
        "validation": {"records": 100, "count_accuracy": 0.90, "single_top3": 0.60},
        "unseen_team": {"records": 1, "count_accuracy": 0.0, "single_top3": 0.0},
        "temporal": {"records": 1, "count_accuracy": 0.0, "single_top3": 0.0},
    }
    gate = fidelity_gate(reports)
    assert gate["passed"]
    assert gate["purpose"] == "fidelity_filter_only_gameplay_strength_unproven"
    reports["temporal"]["records"] = 0
    assert not fidelity_gate(reports)["passed"]


def test_split_counts_reads_explicit_audited_splits(tmp_path):
    shard = tmp_path / "rows.jsonl.gz"
    with gzip.open(shard, "wt", encoding="utf-8") as handle:
        for split in ("train", "train", "validation", "temporal"):
            handle.write(json.dumps({"split": split}) + "\n")
    assert split_counts(shard) == {"train": 2, "validation": 1, "temporal": 1}
