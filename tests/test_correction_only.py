import gzip
import json

import numpy as np
import pytest
import torch

from ptcg_ai.features import DecisionFeatures
import training.train_correction_only as correction_only
from training.train_correction_only import (
    _certification_kind,
    audit_eligible,
    correction_collate,
    correction_partition,
    correction_split,
    correction_objective,
    episode_key,
    iter_rehearsal_split,
    migrate_features_to_schema3,
    model_behavior_digest,
    model_action,
    numpy_decision_audit,
    relabel_rehearsal_rows,
    semantic_action,
    semantic_equivalence_sets,
    select_and_gate_final_holdout,
    select_stable,
    stable_fraction,
    stratified_batches,
)


def _features(version=2):
    return {
        "feature_version": version,
        "global": [0.0] * 118,
        "tokens": [0],
        "options": [
            {
                "option_type": 1,
                "context": 0,
                "source_card": 646,
                "target_card": 0,
                "attack_id": 0,
                "area": 1,
                "in_play_area": 0,
                "numeric": [0.0] * (12 if version == 2 else 13),
                "source_serial": 42,
                "target_serial": 0,
            }
        ],
    }


def test_schema2_migration_is_copy_and_adds_only_zero_flag():
    original = _features(2)
    migrated = migrate_features_to_schema3(original)

    assert original["feature_version"] == 2
    assert len(original["options"][0]["numeric"]) == 12
    assert migrated["feature_version"] == 3
    assert migrated["options"][0]["numeric"] == [0.0] * 13
    DecisionFeatures.from_json(migrated)


def test_semantic_action_does_not_depend_on_option_index():
    features = _features(3)
    second = dict(features["options"][0])
    second["source_card"] = 648
    second["source_serial"] = 99
    features["options"].append(second)
    reversed_features = dict(features)
    reversed_features["options"] = list(reversed(features["options"]))

    assert semantic_action(features, [1]) == semantic_action(reversed_features, [0])


def test_semantic_action_keeps_number_but_drops_transient_indices():
    features = _features(3)
    first = features["options"][0]
    second = dict(first)
    first["numeric"] = [0.1, 0.2] + [0.0] * 7 + [0.1, 0.2, 0.3, 0.0]
    second["numeric"] = [0.1, 0.2] + [0.0] * 7 + [0.9, 0.8, 0.7, 0.0]
    features["options"] = [first, second]
    assert semantic_action(features, [0]) == semantic_action(features, [1])
    second["numeric"][0] = 0.5
    assert semantic_action(features, [0]) != semantic_action(features, [1])


def test_schema_migration_rejects_bad_shape_and_nonfinite_values():
    malformed = _features(2)
    malformed["global"].pop()
    with pytest.raises(ValueError, match="global vector"):
        migrate_features_to_schema3(malformed)
    nonfinite = _features(2)
    nonfinite["options"][0]["numeric"][0] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        migrate_features_to_schema3(nonfinite)


def test_correction_split_is_episode_atomic_and_deterministic():
    rows = [
        {"episode_id": episode, "seat": 0, "step": step}
        for episode in ("a", "b", "c", "d", "e")
        for step in (1, 2)
    ]
    train = correction_split(rows, "train", 0.4)
    holdout = correction_split(rows, "holdout", 0.4)

    assert {row["episode_id"] for row in train}.isdisjoint(
        {row["episode_id"] for row in holdout}
    )
    assert sorted(train + holdout, key=lambda row: (row["episode_id"], row["step"])) == sorted(
        rows, key=lambda row: (row["episode_id"], row["step"])
    )
    assert stable_fraction("same") == stable_fraction("same")


def test_nested_correction_partition_is_episode_atomic_and_seals_holdout():
    rows = [
        {"episode_id": f"episode-{index}", "seat": 0, "step": step}
        for index in range(40)
        for step in (1, 2)
    ]
    partitions = {
        split: correction_partition(rows, split, 0.20, 0.15)
        for split in ("train", "validation", "holdout")
    }
    episode_sets = {
        split: {row["episode_id"] for row in values}
        for split, values in partitions.items()
    }
    assert all(episode_sets.values())
    assert episode_sets["train"].isdisjoint(episode_sets["validation"])
    assert episode_sets["train"].isdisjoint(episode_sets["holdout"])
    assert episode_sets["validation"].isdisjoint(episode_sets["holdout"])
    assert sorted(
        sum(partitions.values(), []), key=lambda row: (row["episode_id"], row["step"])
    ) == sorted(rows, key=lambda row: (row["episode_id"], row["step"]))
    historical_holdout = {
        row["episode_id"] for row in correction_split(rows, "holdout", 0.20)
    }
    assert episode_sets["holdout"] == historical_holdout


def test_stable_selection_is_bounded_and_order_independent():
    rows = [
        {"episode_id": str(index), "seat": 0, "step": index}
        for index in range(30)
    ]
    selected = select_stable(rows, 7, "unit")
    reversed_selected = select_stable(reversed(rows), 7, "unit")

    assert [row["episode_id"] for row in selected] == [
        row["episode_id"] for row in reversed_selected
    ]
    assert len(selected) == 7


def test_stable_selection_zero_is_empty_and_conflicting_duplicate_rejects():
    rows = [
        {"episode_id": "same", "seat": 0, "step": 1, "value": 1},
        {"episode_id": "same", "seat": 0, "step": 1, "value": 2},
    ]
    assert select_stable(rows, 0, "unit") == []
    with pytest.raises(ValueError, match="conflicting duplicate"):
        select_stable(rows, 2, "unit")
    with pytest.raises(ValueError, match="negative"):
        select_stable(rows, -1, "unit")


def test_rehearsal_split_is_episode_atomic_and_excludes_corrections(tmp_path):
    path = tmp_path / "rows.jsonl.gz"
    rows = [
        {"episode_id": episode, "seat": seat, "step": step}
        for episode in ("a", "b", "c", "excluded")
        for seat in (0, 1)
        for step in (1, 2)
    ]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    excluded = frozenset({"excluded"})
    train = list(iter_rehearsal_split(path, split="train", holdout_fraction=0.5, excluded_episodes=excluded))
    holdout = list(iter_rehearsal_split(path, split="holdout", holdout_fraction=0.5, excluded_episodes=excluded))
    train_episodes = {episode_key(row) for row in train}
    holdout_episodes = {episode_key(row) for row in holdout}
    assert train_episodes.isdisjoint(holdout_episodes)
    assert train_episodes | holdout_episodes == {"a", "b", "c"}
    assert all(sum(episode_key(row) == episode for row in train + holdout) == 4 for episode in ("a", "b", "c"))


def test_model_behavior_digest_normalizes_zero_padded_schema3(tmp_path):
    schema2 = tmp_path / "schema2.npz"
    schema3 = tmp_path / "schema3.npz"
    numeric = np.arange(24, dtype=np.float16).reshape(12, 2)
    common = {"score_w": np.asarray([[1.0]], dtype=np.float16)}
    np.savez_compressed(schema2, model_schema_version=np.asarray(2), numeric_w=numeric, **common)
    np.savez_compressed(
        schema3,
        model_schema_version=np.asarray(3),
        numeric_w=np.concatenate([numeric, np.zeros((1, 2), dtype=np.float16)]),
        **common,
    )
    assert model_behavior_digest(schema2) == model_behavior_digest(schema3)


def test_complete_turn_certification_requires_exact_coverage_anchor_and_half_strict():
    behavior = "A" * 64
    file_hash = "B" * 64
    correction = {
        "anchor_behavior_sha256": behavior,
        "decision": {
            "admitted": True,
            "reason": "admitted",
            "expected_worlds": 8,
            "covered_worlds": 8,
            "noninferior_worlds": 8,
            "strict_better_worlds": 4,
        },
        "coverage": {"baseline": 8, "candidate": 8},
        "worlds": [{} for _ in range(8)],
        "errors": [],
    }
    raw = {"correction": correction}
    assert _certification_kind(raw, anchor_file_sha256=file_hash, anchor_behavior_sha256=behavior) == "complete_turn_v1"
    correction["coverage"]["candidate"] = 7
    assert _certification_kind(raw, anchor_file_sha256=file_hash, anchor_behavior_sha256=behavior) is None
    correction["coverage"]["candidate"] = 8
    correction["anchor_behavior_sha256"] = "C" * 64
    assert _certification_kind(raw, anchor_file_sha256=file_hash, anchor_behavior_sha256=behavior) is None


def test_rehearsal_relabel_ignores_replay_action_and_uses_exact_anchor_order():
    features = _features(3)
    second = dict(features["options"][0])
    second["source_card"] = 648
    features["options"].append(second)
    features["global"][28] = features["global"][29] = 1 / 9

    class Anchor:
        @staticmethod
        def predict(_features):
            return np.asarray([0.0, 2.0]), np.zeros(61), 0.0

    raw = {"episode_id": "e", "seat": 0, "step": 1, "action": [0], "features": features}
    relabeled = relabel_rehearsal_rows([raw], Anchor())
    assert relabeled[0]["action"] == [1]
    assert relabeled[0]["sample_source"] == "anchor_rehearsal"
    assert raw["action"] == [0]


def test_audit_gate_uses_integer_change_budget_and_requires_exact_anchor_labels():
    audit = {
        "rehearsal_records": 100,
        "correction_records": 10,
        "rehearsal_changed": 1,
        "rehearsal_base_label_exact": 100,
        "correction_base_label_exact": 0,
        "correction_lift": 0.2,
    }
    assert audit_eligible(audit, max_change_rate=0.01, min_correction_lift=0.08) == (True, 1)
    audit["rehearsal_changed"] = 2
    assert audit_eligible(audit, max_change_rate=0.01, min_correction_lift=0.08) == (False, 1)
    audit["rehearsal_changed"] = 1
    audit["rehearsal_base_label_exact"] = 99
    assert audit_eligible(audit, max_change_rate=0.01, min_correction_lift=0.08)[0] is False


def _training_row(source, action, *, episode="episode", duplicate=False):
    features = _features(3)
    other = dict(features["options"][0])
    other["source_card"] = features["options"][0]["source_card"] if duplicate else 648
    other["source_serial"] = features["options"][0]["source_serial"] if duplicate else 99
    other["numeric"] = list(features["options"][0]["numeric"])
    if duplicate:
        other["numeric"][9] = 1.0
    features["options"].append(other)
    features["global"][28] = features["global"][29] = 1 / 9
    row = {
        "episode_id": episode,
        "seat": 0,
        "step": 1,
        "action": list(action),
        "reward": 0.0,
        "features": features,
        "sample_weight": 8.0 if source == "correction" else 1.0,
        "sample_source": source,
    }
    if source == "correction":
        row["action_equivalence"] = semantic_equivalence_sets(features, action)
    return row


def _objective_gradient(rehearsal_count):
    rows = [_training_row("correction", [1], episode="correction")]
    rows.extend(
        _training_row("anchor_rehearsal", [0], episode=f"rehearsal-{index}")
        for index in range(rehearsal_count)
    )
    batch = correction_collate(rows)
    logits = torch.zeros(len(rows) * 2, requires_grad=True)
    counts = torch.zeros((len(rows), 61), requires_grad=True)
    loss, _ = correction_objective(
        logits,
        counts,
        torch.zeros_like(logits),
        torch.zeros_like(counts),
        batch,
        2.0,
    )
    loss.backward()
    return logits.grad.detach().clone()


def test_rehearsal_has_no_hard_label_sharpening_and_cannot_dilute_correction_ce():
    one_rehearsal = _objective_gradient(1)
    ten_rehearsals = _objective_gradient(10)

    # At the exact anchor, KL has zero gradient.  The only gradient is the
    # correction label: rehearsal argmax labels do not sharpen their logits.
    assert torch.allclose(one_rehearsal[2:], torch.zeros_like(one_rehearsal[2:]), atol=1e-7)
    assert torch.allclose(ten_rehearsals[2:], torch.zeros_like(ten_rehearsals[2:]), atol=1e-7)
    assert torch.allclose(one_rehearsal[:2], ten_rehearsals[:2], atol=1e-7)
    assert one_rehearsal[0] > 0 and one_rehearsal[1] < 0


def test_semantic_duplicate_is_a_label_set_for_training_and_audit():
    row = _training_row("correction", [1], episode="duplicate", duplicate=True)
    assert row["action_equivalence"] == [[0, 1]]
    batch = correction_collate([row])
    logits = torch.tensor([5.0, -5.0], requires_grad=True)
    counts = torch.zeros((1, 61), requires_grad=True)
    loss, components = correction_objective(
        logits,
        counts,
        logits.detach().clone(),
        counts.detach().clone(),
        batch,
        0.0,
    )
    assert float(components["action"].detach()) == pytest.approx(0.0, abs=1e-7)

    class FixedModel:
        def __init__(self, scores):
            self.scores = np.asarray(scores, dtype=np.float32)

        def predict(self, _features):
            return self.scores, np.zeros(61, dtype=np.float32), 0.0

    # Student chooses concrete index 0 while the stored correction names index
    # 1.  The semantic label succeeds, but exact-index telemetry still records
    # the distinction.
    audit = numpy_decision_audit(FixedModel([5.0, -5.0]), FixedModel([-5.0, 5.0]), [row], [])
    assert audit["correction_label_exact"] == 0
    assert audit["correction_label_semantic"] == 1
    assert audit["correction_label_rate"] == 1.0


def test_stratified_batches_are_deterministic_bounded_and_always_corrective():
    corrections = [
        {"sample_source": "correction", "episode_id": f"c-{index}"}
        for index in range(3)
    ]
    rehearsals = [
        {"sample_source": "anchor_rehearsal", "episode_id": f"r-{index}"}
        for index in range(25)
    ]
    rows = corrections + rehearsals
    first = list(stratified_batches(rows, 8, 17))
    second = list(stratified_batches(rows, 8, 17))
    assert first == second
    assert all(len(chunk) <= 8 for chunk in first)
    assert all(any(row["sample_source"] == "correction" for row in chunk) for chunk in first)
    assert {row["episode_id"] for chunk in first for row in chunk if row["sample_source"] == "anchor_rehearsal"} == {
        row["episode_id"] for row in rehearsals
    }


def test_final_holdout_is_opened_once_after_validation_selection_without_fallback(
    monkeypatch, tmp_path
):
    outputs = []
    runs = []
    for seed, lift in ((2, 0.2), (1, 0.1)):
        output = tmp_path / f"seed-{seed}.npz"
        output.write_bytes(b"candidate")
        outputs.append(output)
        runs.append({
            "seed": seed,
            "qualified": True,
            "output": str(output),
            "sha256": "hash",
            "validation_artifact_audit": {
                "correction_lift": lift,
                "rehearsal_change_rate": 0.0,
            },
        })
    reads = []
    audits = []
    monkeypatch.setattr(
        correction_only,
        "read_rows",
        lambda path: reads.append(str(path)) or [{"source": str(path)}],
    )
    monkeypatch.setattr(correction_only, "NumpyPolicyModel", lambda path: str(path))
    failed_audit = {
        "rehearsal_records": 100,
        "correction_records": 10,
        "rehearsal_changed": 0,
        "rehearsal_base_label_exact": 100,
        "correction_base_label_semantic": 0,
        "correction_lift": 0.0,
    }
    monkeypatch.setattr(
        correction_only,
        "numpy_decision_audit",
        lambda *args: audits.append(args) or dict(failed_audit),
    )

    selected = select_and_gate_final_holdout(
        runs,
        anchor_path=tmp_path / "anchor.npz",
        correction_holdout_path=tmp_path / "correction_holdout.jsonl.gz",
        rehearsal_holdout_path=tmp_path / "rehearsal_holdout.jsonl.gz",
        max_change_rate=0.01,
        min_correction_lift=0.08,
    )
    assert selected == 0
    assert len(reads) == 2
    assert len(audits) == 1
    assert runs[0]["qualified"] is False
    assert not outputs[0].exists()
    # The lower-validation seed is never tried after the selected seed fails.
    assert runs[1]["selected_for_final_holdout"] is False
    assert outputs[1].exists()
