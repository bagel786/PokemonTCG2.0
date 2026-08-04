import gzip
import json
from pathlib import Path

import pytest

import scripts.run_azure_lucario as azure_lucario
from scripts.expand_lucario_replays import timeline_sample
from training.lucario_data import assign_episode_splits, assign_grouped_splits, build_replay_view, canonical_deck
from training.run_lucario_curriculum import (
    aggregate_matchups,
    build_grim_handoff,
    curriculum_status,
    load_resumable_stage,
    merge_rollouts,
    qualification,
    recoverable_understrength,
    variant_game_allocation,
)
from training.train_bc import replay_split


def write_deck(path: Path, cards: list[int]) -> None:
    path.write_text("\n".join(map(str, cards)) + "\n")


def write_gzip(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_canonical_deck_ignores_serialization_order():
    assert canonical_deck([678, 6, 677]) == canonical_deck([6, 677, 678])


def test_timeline_sample_is_deterministic_and_spans_history():
    episodes = [{"id": index, "createTime": f"{index:03d}"} for index in range(100)]
    sample = timeline_sample(list(reversed(episodes)), 5)
    assert [row["id"] for row in sample] == [0, 25, 50, 74, 99]


def test_stratified_splits_are_episode_level_and_cover_every_stratum():
    episodes = [
        {"episode_id": f"{variant}-{reward}-{index}", "variant": variant, "reward": reward}
        for variant in ("variant_1", "variant_2")
        for reward in (0.0, 1.0)
        for index in range(6)
    ]
    first = assign_episode_splits(episodes, seed=7)
    second = assign_episode_splits(list(reversed(episodes)), seed=7)
    assert first == second
    assert len(first) == len(episodes)
    for variant in ("variant_1", "variant_2"):
        for reward in (0.0, 1.0):
            ids = {row["episode_id"] for row in episodes if row["variant"] == variant and row["reward"] == reward}
            assert {first[episode_id] for episode_id in ids} == {"train", "validation", "holdout"}


def test_replay_builder_filters_exact_signatures_without_split_leakage(tmp_path):
    deck_1 = tmp_path / "one.csv"
    deck_2 = tmp_path / "two.csv"
    write_deck(deck_1, [6, 677, 678])
    write_deck(deck_2, [6, 6, 677, 678])
    rows = []
    for variant, deck in (("one", [678, 677, 6]), ("two", [678, 6, 677, 6])):
        for reward in (0.0, 1.0):
            for index in range(4):
                episode = f"{variant}-{reward}-{index}"
                for step in range(2):
                    rows.append({"episode_id": episode, "deck": deck, "reward": reward, "step": step})
    rows.append({"episode_id": "noise", "deck": [1, 2, 3], "reward": 1.0})
    source = tmp_path / "source.jsonl.gz"
    output = tmp_path / "filtered.jsonl.gz"
    manifest_path = tmp_path / "manifest.json"
    write_gzip(source, rows)
    manifest = build_replay_view(source, [deck_1, deck_2], output, manifest_path, seed=3)
    assert manifest["episodes"] == 16
    assert manifest["decisions"] == 32
    observed = {}
    with gzip.open(output, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            observed.setdefault(row["episode_id"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in observed.values())
    assert "noise" not in observed


def test_replay_builder_supports_one_sparse_matchup_deck(tmp_path):
    deck = tmp_path / "bellibolt.csv"
    write_deck(deck, [4, 265, 268])
    rows = [
        {
            "episode_id": f"ep-{index}", "seat": index % 2, "step": 1,
            "deck": [268, 4, 265], "reward": float(index % 2),
            "team": f"team-{index}", "created_at": f"2026-08-{index + 1:02d}T00:00:00Z",
            "features": {"options": [{"context": 0}]},
        }
        for index in range(8)
    ]
    rows.append({
        "episode_id": "noise", "seat": 0, "step": 1, "deck": [1, 2, 3],
        "reward": 1.0, "team": "noise", "features": {"options": [{"context": 0}]},
    })
    source = tmp_path / "source.jsonl.gz"
    output = tmp_path / "filtered.jsonl.gz"
    manifest_path = tmp_path / "manifest.json"
    write_gzip(source, rows)
    manifest = build_replay_view(source, [deck], output, manifest_path, seed=11)
    assert manifest["episodes"] == 8
    assert manifest["decisions"] == 8
    assert list(manifest["variants"]) == ["variant_1"]
    with gzip.open(output, "rt", encoding="utf-8") as handle:
        observed = {json.loads(line)["episode_id"] for line in handle}
    assert observed == {f"ep-{index}" for index in range(8)}


def test_grouped_splits_are_deterministic_and_team_disjoint():
    episodes = [
        {
            "episode_id": f"ep-{index}", "variant": f"variant_{index % 2 + 1}",
            "reward": float(index % 3 == 0), "team": f"team-{index}",
            "created_at": f"2026-08-{index + 1:02d}T00:00:00Z",
        }
        for index in range(20)
    ]
    first = assign_grouped_splits(episodes, seed=9)
    second = assign_grouped_splits(list(reversed(episodes)), seed=9)
    assert first == second
    memberships = {}
    for row in episodes:
        memberships.setdefault(row["team"], set()).add(first[row["episode_id"]])
    assert all(len(values) == 1 for values in memberships.values())
    assert {"train", "validation", "unseen_team", "temporal"} <= set(first.values())


def test_replay_builder_deduplicates_sources_and_weights_wins(tmp_path):
    deck_1, deck_2 = tmp_path / "d1.csv", tmp_path / "d2.csv"
    write_deck(deck_1, [6, 677, 678])
    write_deck(deck_2, [6, 6, 677, 678])
    rows = []
    for index in range(20):
        deck = [6, 677, 678] if index % 2 == 0 else [6, 6, 677, 678]
        rows.append({
            "episode_id": f"ep-{index}", "seat": index % 2, "step": 1, "deck": deck,
            "reward": float(index % 3 == 0), "team": f"team-{index}",
            "created_at": f"2026-08-{index + 1:02d}T00:00:00Z", "features": {"options": [{"context": index % 4}]},
        })
    first, second = tmp_path / "a.jsonl.gz", tmp_path / "b.jsonl.gz"
    write_gzip(first, rows)
    write_gzip(second, rows)
    output, manifest_path = tmp_path / "out.jsonl.gz", tmp_path / "manifest.json"
    manifest = build_replay_view([first, second], [deck_1, deck_2], output, manifest_path, seed=5)
    assert manifest["decisions"] == len(rows)
    assert manifest["duplicate_records_removed"] == len(rows)
    groups = manifest["split_groups"]
    assert not (set(groups["train"]) & set(groups["unseen_team"]))
    with gzip.open(output, "rt", encoding="utf-8") as handle:
        train = [json.loads(line) for line in handle if '"split":"train"' in line]
    assert train and all(row["sample_weight"] > 0 for row in train)


def test_explicit_replay_split_excludes_holdout_from_training():
    assert replay_split({"episode_id": "x", "split": "train"}) == "train"
    assert replay_split({"episode_id": "x", "split": "validation"}) == "validation"
    assert replay_split({"episode_id": "x", "split": "holdout"}) == "holdout"
    with pytest.raises(ValueError):
        replay_split({"episode_id": "x", "split": "test"})


def test_rollout_merge_preserves_equal_variant_streams(tmp_path):
    streams = []
    for variant in (1, 2):
        path = tmp_path / f"v{variant}.jsonl.gz"
        write_gzip(path, [
            {"trajectory_id": f"v{variant}-g{game}", "decision_index": 0}
            for game in range(3)
        ])
        streams.append(path)
    report = merge_rollouts(streams, tmp_path / "combined.jsonl.gz")
    assert report["decisions"] == 6
    assert report["trajectories_with_decisions"] == 6
    assert report["variants"]["variant_1"]["decisions"] == report["variants"]["variant_2"]["decisions"]


def test_variant_game_allocation_is_exact_and_equal():
    assert variant_game_allocation(5_000) == {"variant_1": 2_500, "variant_2": 2_500}
    with pytest.raises(ValueError):
        variant_game_allocation(5_001)


def test_resume_requires_an_intact_checkpoint(tmp_path):
    model = tmp_path / "candidate.npz"
    model.write_bytes(b"candidate")
    from training.lucario_data import sha256_file

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"candidate": {"path": str(model), "sha256": sha256_file(model)}}))
    report, resumed_model = load_resumable_stage(report_path)
    assert resumed_model == model
    assert report["candidate"]["path"] == str(model)
    model.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError):
        load_resumable_stage(report_path)


def matchup(rate_1: float, rate_2: float, games: int = 100) -> dict:
    reports = [
        {"variant": "variant_1", "games": games, "wins_a": round(rate_1 * games), "hero_policy_errors": 0, "opponent_policy_errors": 0},
        {"variant": "variant_2", "games": games, "wins_a": round(rate_2 * games), "hero_policy_errors": 0, "opponent_policy_errors": 0},
    ]
    return aggregate_matchups(reports)


def test_qualification_boundaries_and_budget_statuses():
    frozen = matchup(0.35, 0.55)
    unseen = matchup(0.40, 0.60)
    gate = qualification(frozen, fidelity_delta=-0.03, kl_rollback=False, unseen=unseen)
    assert gate["passed"]
    report = {"qualification": gate, "frozen_evaluation": frozen}
    assert curriculum_status(report, 5_000, 20_000) == "qualified"

    weak = matchup(0.20, 0.30)
    weak_gate = qualification(weak, fidelity_delta=0.0, kl_rollback=False, unseen=unseen)
    weak_report = {"qualification": weak_gate, "frozen_evaluation": weak}
    assert recoverable_understrength(weak_report)
    assert curriculum_status(weak_report, 5_000, 20_000) == "needs_more_training"
    assert curriculum_status(weak_report, 20_000, 20_000) == "failed_at_budget_cap"

    too_weak = matchup(0.19, 0.35)
    too_weak_report = {
        "qualification": qualification(too_weak, fidelity_delta=0.0, kl_rollback=False, unseen=unseen),
        "frozen_evaluation": too_weak,
    }
    assert not recoverable_understrength(too_weak_report)
    assert curriculum_status(too_weak_report, 5_000, 20_000) == "failed_understrength"


def test_grim_handoff_assigns_exactly_25_percent_lucario_weight(tmp_path):
    base = tmp_path / "league.json"
    base.write_text(json.dumps({"version": 1, "opponents": [
        {"name": "a", "train_weight": 2},
        {"name": "b", "train_weight": 1},
    ]}))
    model = tmp_path / "lucario.npz"
    model.write_bytes(b"model")
    grim = tmp_path / "grim.npz"
    grim.write_bytes(b"grim")
    decks = [tmp_path / "d1.csv", tmp_path / "d2.csv"]
    for deck in decks:
        write_deck(deck, [6] * 60)
    output = tmp_path / "next.json"
    handoff = build_grim_handoff(base, model, decks, grim, output)
    league = json.loads(output.read_text())
    weights = {row["name"]: row["train_weight"] for row in league["opponents"]}
    assert sum(weights.values()) == pytest.approx(100.0)
    assert weights["mega_lucario_qualified_variant_1"] + weights["mega_lucario_qualified_variant_2"] == 25.0
    assert handoff["initial_grim_model"] == str(grim)


def test_post_sync_verification_checks_models_rollouts_and_replay_view(tmp_path, monkeypatch):
    monkeypatch.setattr(azure_lucario, "ROOT", tmp_path)
    output = tmp_path / "artifacts" / "lucario_run"
    data_dir = output / "data"
    stage_dir = output / "stage_001"
    data_dir.mkdir(parents=True)
    stage_dir.mkdir(parents=True)
    selected = stage_dir / "policy.npz"
    rollouts = stage_dir / "rollouts.jsonl.gz"
    replay_view = data_dir / "view.jsonl.gz"
    selected.write_bytes(b"selected")
    rollouts.write_bytes(b"rollouts")
    replay_view.write_bytes(b"replays")
    from training.lucario_data import sha256_file

    remote = Path("/mnt/ptcg/repo/artifacts/lucario_run")
    stage_report = {
        "candidate": {"path": str(remote / "stage_001/policy.npz"), "sha256": sha256_file(selected)},
        "rollouts": {"output": str(remote / "stage_001/rollouts.jsonl.gz"), "sha256": sha256_file(rollouts)},
    }
    (stage_dir / "report.json").write_text(json.dumps(stage_report))
    (data_dir / "manifest.json").write_text(json.dumps({
        "output": str(remote / "data/view.jsonl.gz"), "output_sha256": sha256_file(replay_view),
    }))
    (output / "final_report.json").write_text(json.dumps({
        "selected_model": str(remote / "stage_001/policy.npz"),
        "selected_sha256": sha256_file(selected),
        "stages": [str(remote / "stage_001/report.json")],
    }))
    verification = azure_lucario.verify_synced_artifacts(output)
    assert verification["passed"]
    assert len(verification["checked"]) == 4


def test_azure_budget_seconds_rejects_exhausted_budget():
    assert azure_lucario.remaining_budget_seconds(30.0, 0.5, 10.0) == 180_000
    assert azure_lucario.remaining_budget_seconds(30.0, 0.5, 60.0) == 0
    with pytest.raises(ValueError):
        azure_lucario.remaining_budget_seconds(30.0, 0.0, 0.0)
