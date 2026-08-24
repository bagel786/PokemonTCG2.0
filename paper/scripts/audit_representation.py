#!/usr/bin/env python3
"""Audit PLAY source-identity omission and output-module policy disagreement.

This script uses the frozen, identity-aware feature rows.  It reconstructs the
historical blind v2 option input by zeroing ``source_card`` for ordinary PLAY
options.  Runtime shields are intentionally not invoked; the policy comparisons
here are mechanistic neural-head diagnostics, not gameplay outcomes.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
PLAY = 7
OPTION_NAMES = {
    0: "number", 1: "yes", 2: "no", 3: "card", 4: "tool_card",
    5: "energy_card", 6: "energy", 7: "play", 8: "attach", 9: "evolve",
    10: "ability", 11: "discard", 12: "retreat", 13: "attack", 14: "end",
    15: "skill", 16: "special_condition",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()


def load_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


def ordinary_play_indices(row: dict) -> list[int]:
    indices = []
    legal = row.get("legal_options") or []
    features = row["features"]["options"]
    for index, option in enumerate(features):
        if int(option["option_type"]) != PLAY:
            continue
        raw = legal[index] if index < len(legal) else {}
        if raw.get("area") is None:
            indices.append(index)
    return indices


def multi_play_state(row: dict) -> bool:
    cards = {
        int(row["features"]["options"][index].get("source_card", 0) or 0)
        for index in ordinary_play_indices(row)
    }
    cards.discard(0)
    return len(cards) >= 2


def cross_identity_collision_state(row: dict) -> bool:
    """Whether a row contains an exact blind-input collision across identities."""
    groups = defaultdict(list)
    for index in ordinary_play_indices(row):
        option = row["features"]["options"][index]
        groups[blind_option_signature(option)].append(
            int(option.get("source_card", 0) or 0)
        )
    return any(
        len(values) >= 2 and len({card for card in values if card > 0}) >= 2
        for values in groups.values()
    )


def blind_option_signature(option: dict) -> tuple:
    """Exact v2 option-head input except for the intentionally blank source id."""
    return (
        int(option["option_type"]),
        int(option["context"]),
        0,
        int(option["target_card"]),
        int(option["attack_id"]),
        int(option["area"]),
        int(option["in_play_area"]),
        tuple(float(value) for value in option["numeric"]),
    )


def blind_rows(rows: list[dict]) -> list[dict]:
    transformed = []
    for row in rows:
        cloned = dict(row)
        cloned_features = dict(row["features"])
        cloned_options = [dict(option) for option in row["features"]["options"]]
        for index in ordinary_play_indices(row):
            cloned_options[index]["source_card"] = 0
        cloned_features["options"] = cloned_options
        cloned["features"] = cloned_features
        transformed.append(cloned)
    return transformed


def decisions(model, rows: list[dict]) -> list[tuple[int, ...]]:
    from training.replay_refresh import _decision
    from training.train_bc import collate, move

    batch = move(collate(rows), torch.device("cpu"))
    logits, count_logits, _ = model(batch)
    return [
        tuple(sorted(_decision(logits, count_logits, batch, index)))
        for index in range(len(rows))
    ]


def bootstrap_approval(records: list[dict], iterations: int, seed: int) -> dict:
    decisive = [row for row in records if row["cls"] in {"candidate_approved", "control_approved"}]
    candidate = sum(row["cls"] == "candidate_approved" for row in decisive)
    control = len(decisive) - candidate
    abstain = sum(row["cls"] == "abstain" for row in records)
    if not decisive:
        return {
            "candidate_approved": candidate, "control_approved": control,
            "abstain": abstain, "decisive": 0, "approval": None,
            "episode_bootstrap_95_ci": [None, None], "episodes": 0,
        }
    by_episode = defaultdict(list)
    for row in decisive:
        by_episode[str(row["episode_id"])].append(row["cls"] == "candidate_approved")
    episodes = sorted(by_episode)
    numerators = np.asarray([sum(by_episode[key]) for key in episodes], dtype=np.int64)
    denominators = np.asarray([len(by_episode[key]) for key in episodes], dtype=np.int64)
    rng = np.random.default_rng(seed)
    samples = np.empty(iterations, dtype=np.float64)
    batch_size = 2_000
    for start in range(0, iterations, batch_size):
        stop = min(iterations, start + batch_size)
        picked = rng.integers(0, len(episodes), size=(stop - start, len(episodes)))
        samples[start:stop] = numerators[picked].sum(axis=1) / denominators[picked].sum(axis=1)
    return {
        "candidate_approved": candidate,
        "control_approved": control,
        "abstain": abstain,
        "decisive": len(decisive),
        "approval": candidate / len(decisive),
        "episode_bootstrap_95_ci": [
            float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))
        ],
        "episodes": len(episodes),
    }


def grouped_approval(records: list[dict], key, iterations: int, seed: int) -> dict:
    groups = defaultdict(list)
    for row in records:
        groups[str(key(row))].append(row)
    return {
        label: bootstrap_approval(rows, iterations, seed + index)
        for index, (label, rows) in enumerate(sorted(groups.items()))
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus", type=Path,
        default=ROOT / "artifacts/final_sprint/identity_train/merged_decisions.jsonl.gz",
    )
    parser.add_argument(
        "--manifest", type=Path,
        default=ROOT / "artifacts/final_sprint/identity_train/train_manifest.json",
    )
    parser.add_argument(
        "--control-model", type=Path,
        default=ROOT / "artifacts/grim_damage_conversion/winner/extracted/policy_first.npz",
    )
    parser.add_argument(
        "--candidate-model", type=Path,
        default=ROOT / "artifacts/final_sprint/exp23_identity_trained/policy_first.npz",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "paper/data/representation_audit.json",
    )
    parser.add_argument(
        "--card-output", type=Path,
        default=ROOT / "paper/data/representation_source_cards.csv",
    )
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--bootstrap-iterations", type=int, default=20_000)
    return parser.parse_args()


def main() -> int:
    from training.replay_refresh import classify_fresh_row
    from training.train_bc import PolicyNet, load_npz_weights

    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = load_rows(args.corpus)
    source_counts = Counter()
    context_counts = Counter()
    corpus_wide_blind_patterns = defaultdict(Counter)
    play_options = unresolved = bound = 0
    play_states = multi_states = 0
    multi_option_states = multi_option_states_unique_indices = 0
    numeric_indices_matching_raw = 0
    within_state_signature_groups = 0
    within_state_duplicate_groups = 0
    within_state_cross_identity_collisions = 0
    states_with_cross_identity_collision = 0
    collision_instances = 0
    for row in rows:
        indices = ordinary_play_indices(row)
        if indices:
            play_states += 1
        cards = set()
        hand_indices = []
        row_blind_groups = defaultdict(list)
        for index in indices:
            option = row["features"]["options"][index]
            legal = row.get("legal_options") or []
            raw = legal[index] if index < len(legal) else {}
            card = int(option.get("source_card", 0) or 0)
            hand_index = int(raw.get("index", 0) or 0)
            hand_indices.append(hand_index)
            numeric_indices_matching_raw += int(
                len(option.get("numeric", [])) > 9
                and abs(float(option["numeric"][9]) - hand_index / 60.0) < 1e-12
            )
            play_options += 1
            # The historical v2 reconstruction explicitly zeroes this field.
            # Count the omitted coordinate directly rather than treating a raw
            # engine field as a substitute for the policy input.
            unresolved += 1
            bound += int(card > 0)
            cards.add(card)
            source_counts[card] += 1
            context_counts[int(option["context"])] += 1
            signature = blind_option_signature(option)
            row_blind_groups[signature].append(card)
            corpus_wide_blind_patterns[signature][card] += 1
        cards.discard(0)
        multi_states += int(len(cards) >= 2)
        if len(indices) >= 2:
            multi_option_states += 1
            multi_option_states_unique_indices += int(
                len(set(hand_indices)) == len(hand_indices)
            )
        within_state_signature_groups += len(row_blind_groups)
        duplicate_groups = [values for values in row_blind_groups.values() if len(values) >= 2]
        within_state_duplicate_groups += len(duplicate_groups)
        cross_identity = [
            values for values in duplicate_groups
            if len({card for card in values if card > 0}) >= 2
        ]
        within_state_cross_identity_collisions += len(cross_identity)
        states_with_cross_identity_collision += int(bool(cross_identity))
        collision_instances += sum(len(values) for values in cross_identity)

    # These corpus-wide patterns are not action collisions: their observations
    # (and therefore the shared state vector supplied to the head) differ.  They
    # are retained only as a transparent measure of repeated option patterns.
    corpus_wide_multi_identity_patterns = {
        signature: counts for signature, counts in corpus_wide_blind_patterns.items()
        if len({card for card in counts if card > 0}) >= 2
    }
    corpus_wide_multi_identity_instances = sum(
        sum(counts.values()) for counts in corpus_wide_multi_identity_patterns.values()
    )

    control = PolicyNet(2)
    candidate = PolicyNet(2)
    load_npz_weights(control, args.control_model)
    load_npz_weights(candidate, args.candidate_model)
    control.eval().cpu()
    candidate.eval().cpu()

    comparison_rows = []
    with torch.no_grad():
        for start in range(0, len(rows), args.batch_size):
            original = rows[start:start + args.batch_size]
            blinded = blind_rows(original)
            control_actions = decisions(control, blinded)
            candidate_actions = decisions(candidate, original)
            for row, control_action, candidate_action in zip(
                original, control_actions, candidate_actions, strict=True
            ):
                elite = tuple(sorted(int(index) for index in row["action"]))
                if candidate_action == control_action:
                    cls = "agreement"
                elif candidate_action == elite:
                    cls = "candidate_approved"
                elif control_action == elite:
                    cls = "control_approved"
                else:
                    cls = "abstain"
                selected_types = sorted({
                    int(row["features"]["options"][index]["option_type"])
                    for index in row["action"]
                    if 0 <= index < len(row["features"]["options"])
                })
                comparison_rows.append({
                    "episode_id": row["episode_id"],
                    "team": row.get("team", ""),
                    "split": classify_fresh_row(row, manifest),
                    "hero_order": row.get("hero_order", "unknown"),
                    "turn": int(row.get("turn", -1)),
                    "context": int(row["features"]["options"][0]["context"])
                    if row["features"]["options"] else -1,
                    "action_family": "+".join(OPTION_NAMES.get(value, str(value)) for value in selected_types),
                    "multi_play_identity_state": multi_play_state(row),
                    "cross_identity_collision_state": cross_identity_collision_state(row),
                    "disagree": candidate_action != control_action,
                    "cls": cls,
                })

    def disagreement(group: list[dict]) -> dict:
        disagreements = sum(row["disagree"] for row in group)
        return {
            "decisions": len(group),
            "disagreements": disagreements,
            "rate": disagreements / len(group) if group else None,
        }

    holdout = [row for row in comparison_rows if row["split"] == "team_holdout"]
    split_counts = Counter(row["split"] for row in comparison_rows)
    holdout_disagreements = [row for row in holdout if row["cls"] != "agreement"]
    per_team_named = grouped_approval(
        holdout_disagreements, lambda row: row["team"],
        args.bootstrap_iterations, 2026081601,
    )
    team_ratios = [
        value["approval"] for value in per_team_named.values()
        if value["approval"] is not None
    ]
    # Preserve the team-balanced calculation without releasing private labels.
    per_team = {
        f"team_{index:02d}": value
        for index, (_, value) in enumerate(sorted(per_team_named.items()), start=1)
    }

    report = {
        "schema_version": 2,
        "method": "feature-row neural output-module diagnostic; index-exact actions; no runtime shields",
        "collision_definition": (
            "two simultaneously legal ordinary PLAY options in the same decision row "
            "have identical blind option-head inputs and different repaired source identities"
        ),
        "provenance": {
            "branch_commit": git_commit(),
            "corpus": str(args.corpus.relative_to(ROOT)),
            "corpus_sha256": sha256_file(args.corpus),
            "manifest": str(args.manifest.relative_to(ROOT)),
            "manifest_sha256": sha256_file(args.manifest),
            "control_model_sha256": sha256_file(args.control_model),
            "candidate_model_sha256": sha256_file(args.candidate_model),
            "script": str(Path(__file__).resolve().relative_to(ROOT)),
            "script_sha256": sha256_file(Path(__file__).resolve()),
        },
        "corpus": {
            "decisions": len(rows),
            "split_decisions": {
                key: int(value) for key, value in sorted(split_counts.items())
            },
            "ordinary_play_options": play_options,
            "baseline_unresolved_play_options": unresolved,
            "baseline_unresolved_proportion": unresolved / max(1, play_options),
            "identity_bound_play_options": bound,
            "identity_bound_proportion": bound / max(1, play_options),
            "states_with_play": play_states,
            "states_with_two_or_more_play_options": multi_option_states,
            "multi_play_option_states_with_unique_hand_indices": multi_option_states_unique_indices,
            "play_options_with_numeric_index_matching_raw": numeric_indices_matching_raw,
            "states_with_two_or_more_play_identities": multi_states,
            "multi_identity_proportion_of_play_states": multi_states / max(1, play_states),
            "within_state_blind_signature_groups": within_state_signature_groups,
            "within_state_duplicate_blind_signature_groups": within_state_duplicate_groups,
            "within_state_cross_identity_collision_groups": within_state_cross_identity_collisions,
            "states_with_within_state_cross_identity_collision": states_with_cross_identity_collision,
            "play_option_instances_in_within_state_cross_identity_collisions": collision_instances,
            "within_state_cross_identity_collision_instance_proportion": collision_instances / max(1, play_options),
            "corpus_wide_blind_signature_patterns": len(corpus_wide_blind_patterns),
            "corpus_wide_patterns_with_multiple_source_identities": len(corpus_wide_multi_identity_patterns),
            "play_option_instances_in_corpus_wide_multi_identity_patterns": corpus_wide_multi_identity_instances,
            "by_context": {str(key): value for key, value in sorted(context_counts.items())},
        },
        "head_disagreement": {
            "all": disagreement(comparison_rows),
            "multi_play_identity": disagreement([
                row for row in comparison_rows if row["multi_play_identity_state"]
            ]),
            "other": disagreement([
                row for row in comparison_rows if not row["multi_play_identity_state"]
            ]),
            "exact_collision_state": disagreement([
                row for row in comparison_rows if row["cross_identity_collision_state"]
            ]),
            "non_collision_state": disagreement([
                row for row in comparison_rows if not row["cross_identity_collision_state"]
            ]),
            "team_holdout": disagreement(holdout),
        },
        "refresh_holdout_recorded_action_agreement": {
            "overall": bootstrap_approval(
                holdout_disagreements, args.bootstrap_iterations, 2026081602
            ),
            "by_multi_identity_state": grouped_approval(
                holdout_disagreements,
                lambda row: "multi_play_identity" if row["multi_play_identity_state"] else "other",
                args.bootstrap_iterations, 2026081603,
            ),
            "by_exact_collision_state": {
                "exact_collision": bootstrap_approval(
                    [row for row in holdout_disagreements if row["cross_identity_collision_state"]],
                    args.bootstrap_iterations, 2026081613,
                ),
                "non_collision": bootstrap_approval(
                    [row for row in holdout_disagreements if not row["cross_identity_collision_state"]],
                    args.bootstrap_iterations, 2026081602,
                ),
            },
            "by_team": per_team,
            "team_balanced_approval": float(np.mean(team_ratios)) if team_ratios else None,
            "by_actual_order": grouped_approval(
                holdout_disagreements, lambda row: row["hero_order"],
                args.bootstrap_iterations, 2026081604,
            ),
            "by_turn_band": grouped_approval(
                holdout_disagreements,
                lambda row: "early" if row["turn"] <= 3 else "mid" if row["turn"] <= 7 else "late",
                args.bootstrap_iterations, 2026081605,
            ),
            "by_context": grouped_approval(
                holdout_disagreements, lambda row: row["context"],
                args.bootstrap_iterations, 2026081606,
            ),
            "by_action_family": grouped_approval(
                holdout_disagreements, lambda row: row["action_family"],
                args.bootstrap_iterations, 2026081607,
            ),
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.card_output.parent.mkdir(parents=True, exist_ok=True)
    # Do not emit proprietary card identifiers or names.  Stable anonymous labels
    # are sufficient to reproduce the frequency distribution used in the paper.
    with args.card_output.open("w", encoding="utf-8", newline="") as handle:
        handle.write("anonymous_identity,play_options\n")
        for ordinal, (_, count) in enumerate(source_counts.most_common(), start=1):
            handle.write(f"identity_{ordinal:03d},{count}\n")
    print(json.dumps({
        "output": str(args.output),
        "decisions": len(rows),
        "play_options": play_options,
        "multi_play_states": multi_states,
        "within_state_cross_identity_collision_groups": within_state_cross_identity_collisions,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
