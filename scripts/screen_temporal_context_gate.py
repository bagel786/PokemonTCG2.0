#!/usr/bin/env python3
"""Leakage-safe screen for a learned A2/temporal-continuation gate.

The gate is trained only on Aug-4 exact-Grim winner decisions, selected on
Aug-5, and evaluated once on the frozen Aug-6 holdout.  Inputs are limited to
public policy features and the two models' outputs.  Dataset metadata (team,
opponent, rank, date, outcome, and episode id) is never an input feature.

This is deliberately a feasibility screen, not a packaging script.  It writes
an auditable JSON report but no runnable policy artifact.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
import torch.nn.functional as torch_f

from ptcg_ai.features import DecisionFeatures
from ptcg_ai.model import NumpyPolicyModel


DEFAULT_DATA = ROOT / "artifacts/emergency_strength_sprint/temporal_elite_schema3"
DEFAULT_A2 = DEFAULT_DATA / "a2_schema3_zero_init.npz"
DEFAULT_CONTINUATION = ROOT / "artifacts/elite_policy_candidates/temporal_continue_lr25/policy_weights.npz"
DEFAULT_TRAIN = DEFAULT_DATA / "train_winners_aug4_aug5_rank1_100.jsonl.gz"
DEFAULT_HOLDOUT = DEFAULT_DATA / "holdout_winners_aug6_rank1_100.jsonl.gz"
DEFAULT_OUTPUT = ROOT / "artifacts/elite_policy_candidates/temporal_context_gate_screen/report.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_key(option) -> tuple:
    """Collapse duplicate engine indices that describe the same public move."""
    return (
        int(option.option_type),
        int(option.context),
        int(option.source_card),
        int(option.target_card),
        int(option.attack_id),
        int(option.area),
        int(option.in_play_area),
        tuple(
            round(float(value), 6)
            for index, value in enumerate(option.numeric)
            if index not in (9, 10, 11)
        ),
    )


def softmax_stats(logits: np.ndarray) -> list[float]:
    values = np.asarray(logits, dtype=np.float64)
    centered = values - float(np.max(values))
    probabilities = np.exp(np.clip(centered, -60.0, 0.0))
    probabilities /= max(float(probabilities.sum()), 1e-12)
    ordered = np.sort(values)[::-1]
    top = float(ordered[0])
    second = float(ordered[1]) if len(ordered) > 1 else top
    third = float(ordered[2]) if len(ordered) > 2 else second
    entropy = -float(np.sum(probabilities * np.log(np.maximum(probabilities, 1e-12))))
    normalized_entropy = entropy / max(math.log(max(2, len(values))), 1e-12)
    return [
        float(probabilities.max()),
        top - second,
        top - third,
        float(values.std()),
        float(values.max() - values.min()),
        normalized_entropy,
    ]


def shared_representation(model: NumpyPolicyModel, features: DecisionFeatures) -> np.ndarray:
    weights = model.weights
    token_rows = weights["state_embedding"][np.asarray(features.state_tokens, dtype=np.int64)]
    state = token_rows.sum(axis=0) / np.sqrt(max(1, len(token_rows)))
    global_hidden = np.tanh(
        np.asarray(features.global_features, dtype=np.float32) @ weights["global_w"]
        + weights["global_b"]
    )
    return np.concatenate([state, global_hidden]).astype(np.float32, copy=False)


def choice_representation(model: NumpyPolicyModel, option) -> np.ndarray:
    """Dense public option identity using the frozen A2 embedding dictionary."""
    weights = model.weights
    numeric = np.asarray(option.numeric, dtype=np.float32)
    return np.concatenate(
        [
            weights["card_embedding"][int(option.source_card)],
            weights["card_embedding"][int(option.target_card)],
            weights["attack_embedding"][int(option.attack_id)],
            weights["type_embedding"][int(option.option_type)],
            weights["context_embedding"][min(int(option.context), len(weights["context_embedding"]) - 1)],
            weights["area_embedding"][min(int(option.area), len(weights["area_embedding"]) - 1)],
            weights["area_embedding"][min(int(option.in_play_area), len(weights["area_embedding"]) - 1)],
            numeric,
        ]
    ).astype(np.float32, copy=False)


def public_gate_features(
    features: DecisionFeatures,
    a2: NumpyPolicyModel,
    continuation: NumpyPolicyModel,
    a2_logits: np.ndarray,
    continuation_logits: np.ndarray,
    a2_value: float,
    continuation_value: float,
    a2_index: int,
    continuation_index: int,
) -> tuple[np.ndarray, dict[str, int]]:
    option_count = len(features.options)
    a2_order = np.argsort(-a2_logits, kind="stable")
    continuation_order = np.argsort(-continuation_logits, kind="stable")
    a2_rank_of_continuation = int(np.flatnonzero(a2_order == continuation_index)[0])
    continuation_rank_of_a2 = int(np.flatnonzero(continuation_order == a2_index)[0])

    # Confidence-only prefix.  Keeping exact slice boundaries makes it possible
    # to select a simpler gate without recomputing the corpus.
    confidence = np.asarray(
        [
            *softmax_stats(a2_logits),
            *softmax_stats(continuation_logits),
            float(a2_logits[a2_index] - a2_logits[continuation_index]),
            float(continuation_logits[continuation_index] - continuation_logits[a2_index]),
            a2_rank_of_continuation / max(1, option_count - 1),
            continuation_rank_of_a2 / max(1, option_count - 1),
            math.log1p(option_count),
            math.log1p(len(features.state_tokens)),
            float(a2_value),
            float(continuation_value),
            float(continuation_value - a2_value),
        ],
        dtype=np.float32,
    )
    global_features = np.asarray(features.global_features, dtype=np.float32)
    context = min(int(features.options[0].context), 63)
    context_one_hot = np.zeros(64, dtype=np.float32)
    context_one_hot[context] = 1.0

    a2_shared = shared_representation(a2, features)
    continuation_shared = shared_representation(continuation, features)
    a2_choice = choice_representation(a2, features.options[a2_index])
    continuation_choice = choice_representation(a2, features.options[continuation_index])
    full = np.concatenate(
        [
            confidence,
            global_features,
            context_one_hot,
            a2_shared,
            continuation_shared - a2_shared,
            a2_choice,
            continuation_choice,
            continuation_choice - a2_choice,
        ]
    )
    slices = {
        "confidence": len(confidence),
        "public_global": len(confidence) + len(global_features) + len(context_one_hot),
        "full_public_model": len(full),
    }
    return full, slices


@dataclass
class Disagreement:
    date: str
    episode: str
    rank: int
    target: int  # 1=continuation fixes A2, 0=continuation harms A2, -1=neither matches
    features: np.ndarray


def load_rows(
    paths: list[Path],
    a2: NumpyPolicyModel,
    continuation: NumpyPolicyModel,
    allowed_dates: set[str] | None = None,
):
    summaries: dict[str, Counter] = defaultdict(Counter)
    disagreements: list[Disagreement] = []
    feature_slices = None
    seen: set[tuple[str, int, int]] = set()
    duplicates = 0
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                key = (str(row.get("episode_id", "")), int(row.get("seat", -1)), int(row.get("step", -1)))
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                date = str(row["source_date"])
                if allowed_dates is not None and date not in allowed_dates:
                    continue
                summary = summaries[date]
                rank = int(row.get("team_rank_aug4", 9999))
                hard_summary = summaries[f"{date}|rank1_20"] if rank <= 20 else None
                summary["records"] += 1
                if hard_summary is not None:
                    hard_summary["records"] += 1
                action = [int(index) for index in row.get("action", [])]
                if len(action) != 1:
                    summary["multi_action_excluded"] += 1
                    if hard_summary is not None:
                        hard_summary["multi_action_excluded"] += 1
                    continue
                features = DecisionFeatures.from_json(row["features"])
                if not features.options or not 0 <= action[0] < len(features.options):
                    summary["invalid_excluded"] += 1
                    if hard_summary is not None:
                        hard_summary["invalid_excluded"] += 1
                    continue
                summary["single_action"] += 1
                if hard_summary is not None:
                    hard_summary["single_action"] += 1
                a2_logits, _, a2_value = a2.predict(features)
                continuation_logits, _, continuation_value = continuation.predict(features)
                a2_index = int(np.argmax(a2_logits))
                continuation_index = int(np.argmax(continuation_logits))
                label_key = semantic_key(features.options[action[0]])
                a2_key = semantic_key(features.options[a2_index])
                continuation_key = semantic_key(features.options[continuation_index])
                a2_correct = a2_key == label_key
                continuation_correct = continuation_key == label_key
                summary["a2_correct"] += int(a2_correct)
                summary["continuation_correct"] += int(continuation_correct)
                if hard_summary is not None:
                    hard_summary["a2_correct"] += int(a2_correct)
                    hard_summary["continuation_correct"] += int(continuation_correct)
                if a2_key == continuation_key:
                    summary["semantic_agreement"] += 1
                    if hard_summary is not None:
                        hard_summary["semantic_agreement"] += 1
                    continue
                summary["semantic_disagreement"] += 1
                if hard_summary is not None:
                    hard_summary["semantic_disagreement"] += 1
                if continuation_correct and not a2_correct:
                    target = 1
                    summary["fix"] += 1
                    if hard_summary is not None:
                        hard_summary["fix"] += 1
                elif a2_correct and not continuation_correct:
                    target = 0
                    summary["harm"] += 1
                    if hard_summary is not None:
                        hard_summary["harm"] += 1
                else:
                    target = -1
                    summary["neither"] += 1
                    if hard_summary is not None:
                        hard_summary["neither"] += 1
                vector, slices = public_gate_features(
                    features,
                    a2,
                    continuation,
                    a2_logits,
                    continuation_logits,
                    a2_value,
                    continuation_value,
                    a2_index,
                    continuation_index,
                )
                feature_slices = slices
                disagreements.append(
                    Disagreement(
                        date=date,
                        episode=str(row["episode_id"]),
                        rank=rank,
                        target=target,
                        features=vector,
                    )
                )
    if feature_slices is None:
        raise RuntimeError("no semantic disagreements found")
    return summaries, disagreements, feature_slices, duplicates


def fit_logistic(x: np.ndarray, y: np.ndarray, l2: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0, dtype=np.float64).astype(np.float32)
    std = x.std(axis=0, dtype=np.float64).astype(np.float32)
    std[std < 1e-5] = 1.0
    normalized = np.clip((x - mean) / std, -8.0, 8.0)
    tx = torch.from_numpy(normalized)
    ty = torch.from_numpy(y.astype(np.float32))
    linear = torch.nn.Linear(x.shape[1], 1)
    with torch.no_grad():
        linear.weight.zero_()
        prevalence = min(1.0 - 1e-5, max(1e-5, float(y.mean())))
        linear.bias.fill_(math.log(prevalence / (1.0 - prevalence)))
    optimizer = torch.optim.LBFGS(
        linear.parameters(), max_iter=50, tolerance_grad=1e-7, tolerance_change=1e-9,
        line_search_fn="strong_wolfe"
    )

    def closure():
        optimizer.zero_grad()
        logits = linear(tx).reshape(-1)
        loss = torch_f.binary_cross_entropy_with_logits(logits, ty)
        loss = loss + float(l2) * torch.sum(linear.weight * linear.weight)
        loss.backward()
        return loss

    optimizer.step(closure)
    packed = np.concatenate(
        [
            linear.weight.detach().cpu().numpy().reshape(-1),
            linear.bias.detach().cpu().numpy().reshape(-1),
        ]
    )
    return packed.astype(np.float32), mean, std


def predict_logistic(x: np.ndarray, packed: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    normalized = np.clip((x - mean) / std, -8.0, 8.0)
    logits = normalized @ packed[:-1] + packed[-1]
    return 1.0 / (1.0 + np.exp(-np.clip(logits, -30.0, 30.0)))


def threshold_metrics(records: list[Disagreement], probabilities: np.ndarray, threshold: float) -> dict:
    selected = probabilities >= threshold
    target = np.asarray([record.target for record in records], dtype=np.int8)
    fixes_selected = int(np.sum(selected & (target == 1)))
    harms_selected = int(np.sum(selected & (target == 0)))
    neither_selected = int(np.sum(selected & (target == -1)))
    decisive = target >= 0
    classifier_correct = int(np.sum((selected == (target == 1)) & decisive))
    return {
        "threshold": float(threshold),
        "semantic_disagreements": len(records),
        "actions_switched_to_continuation": int(selected.sum()),
        "fixes_selected": fixes_selected,
        "harms_selected": harms_selected,
        "neither_selected": neither_selected,
        "net_correct_vs_a2": fixes_selected - harms_selected,
        "decisive_gate_accuracy": classifier_correct / max(1, int(decisive.sum())),
        "selected_decisive_precision": fixes_selected / max(1, fixes_selected + harms_selected),
        "disagreement_coverage": float(selected.mean()) if len(selected) else 0.0,
    }


def choose_threshold(records: list[Disagreement], probabilities: np.ndarray) -> dict:
    candidates = np.linspace(0.30, 0.80, 21)
    results = [threshold_metrics(records, probabilities, float(threshold)) for threshold in candidates]
    # Prefer higher net correct, then lower coverage, then a threshold closer to 0.5.
    return max(
        results,
        key=lambda item: (
            item["net_correct_vs_a2"],
            -item["actions_switched_to_continuation"],
            -abs(item["threshold"] - 0.5),
        ),
    )


def bootstrap_episode_ci(
    records: list[Disagreement],
    selected: np.ndarray,
    singles_by_episode: dict[str, int],
    reference: str,
) -> list[float]:
    contributions = defaultdict(int)
    for record, choose_continuation in zip(records, selected):
        if reference == "a2" and choose_continuation:
            contributions[record.episode] += int(record.target == 1) - int(record.target == 0)
        elif reference == "continuation" and not choose_continuation:
            contributions[record.episode] += int(record.target == 0) - int(record.target == 1)
    episodes = sorted(singles_by_episode)
    numerators = np.asarray([contributions[episode] for episode in episodes], dtype=np.float64)
    denominators = np.asarray([singles_by_episode[episode] for episode in episodes], dtype=np.float64)
    rng = np.random.default_rng(20260825)
    estimates = np.empty(10000, dtype=np.float64)
    for offset in range(0, len(estimates), 250):
        size = min(250, len(estimates) - offset)
        draws = rng.integers(0, len(episodes), size=(size, len(episodes)))
        estimates[offset : offset + size] = (
            numerators[draws].sum(axis=1) / np.maximum(1.0, denominators[draws].sum(axis=1))
        )
    return [float(value) for value in np.quantile(estimates, [0.025, 0.975])]


def scope_report(
    name: str,
    date: str,
    summary: Counter,
    records: list[Disagreement],
    probabilities: np.ndarray,
    threshold: float,
    singles_by_episode: dict[str, int] | None = None,
) -> dict:
    gate = threshold_metrics(records, probabilities, threshold)
    single = int(summary["single_action"])
    a2_correct = int(summary["a2_correct"])
    continuation_correct = int(summary["continuation_correct"])
    gate_correct = a2_correct + int(gate["net_correct_vs_a2"])
    oracle_correct = a2_correct + int(summary["fix"])
    result = {
        "scope": name,
        "date": date,
        "single_action_records": single,
        "multi_action_records_excluded": int(summary["multi_action_excluded"]),
        "semantic_disagreements": int(summary["semantic_disagreement"]),
        "fix_harm_neither": {
            "fix": int(summary["fix"]),
            "harm": int(summary["harm"]),
            "neither": int(summary["neither"]),
        },
        "semantic_top1": {
            "a2": {"correct": a2_correct, "rate": a2_correct / single},
            "continuation": {"correct": continuation_correct, "rate": continuation_correct / single},
            "gate": {"correct": gate_correct, "rate": gate_correct / single},
            "two_policy_oracle_ceiling": {"correct": oracle_correct, "rate": oracle_correct / single},
        },
        "uplift_percentage_points_vs_a2": {
            "continuation": 100.0 * (continuation_correct - a2_correct) / single,
            "gate": 100.0 * (gate_correct - a2_correct) / single,
            "two_policy_oracle_ceiling": 100.0 * (oracle_correct - a2_correct) / single,
        },
        "gate": gate,
        "all_single_action_coverage": gate["actions_switched_to_continuation"] / single,
    }
    if singles_by_episode:
        selected = probabilities >= threshold
        result["gate_uplift_vs_a2_episode_cluster_bootstrap_95"] = [
            100.0 * value for value in bootstrap_episode_ci(records, selected, singles_by_episode, "a2")
        ]
        result["gate_uplift_vs_continuation_percentage_points"] = (
            100.0 * (gate_correct - continuation_correct) / single
        )
        result["gate_uplift_vs_continuation_episode_cluster_bootstrap_95"] = [
            100.0 * value
            for value in bootstrap_episode_ci(records, selected, singles_by_episode, "continuation")
        ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a2", type=Path, default=DEFAULT_A2)
    parser.add_argument("--continuation", type=Path, default=DEFAULT_CONTINUATION)
    parser.add_argument("--train", type=Path, default=DEFAULT_TRAIN)
    parser.add_argument("--holdout", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    torch.manual_seed(20260825)
    torch.set_num_threads(1)
    a2 = NumpyPolicyModel(args.a2)
    continuation = NumpyPolicyModel(args.continuation)
    summaries, disagreements, slices, duplicates = load_rows(
        [args.train, args.holdout], a2, continuation
    )
    by_date = {
        date: [record for record in disagreements if record.date == date]
        for date in ("2026-08-04", "2026-08-05", "2026-08-06")
    }
    if any(not records for records in by_date.values()):
        raise RuntimeError("expected non-empty Aug-4/Aug-5/Aug-6 disagreement sets")

    l2_values = (1e-3, 1e-2, 1e-1)
    candidates = []
    fitted = {}
    train_records = [record for record in by_date["2026-08-04"] if record.target >= 0]
    validation_records = by_date["2026-08-05"]
    for feature_name, width in slices.items():
        train_x = np.stack([record.features[:width] for record in train_records])
        train_y = np.asarray([record.target for record in train_records], dtype=np.float32)
        validation_x = np.stack([record.features[:width] for record in validation_records])
        for l2 in l2_values:
            packed, mean, std = fit_logistic(train_x, train_y, l2)
            probabilities = predict_logistic(validation_x, packed, mean, std)
            threshold_result = choose_threshold(validation_records, probabilities)
            candidate = {
                "feature_set": feature_name,
                "feature_count": width,
                "l2": l2,
                "validation": threshold_result,
            }
            candidates.append(candidate)
            fitted[(feature_name, l2)] = (packed, mean, std)

    selected_candidate = max(
        candidates,
        key=lambda item: (
            item["validation"]["net_correct_vs_a2"],
            -item["feature_count"],
            item["l2"],
            -item["validation"]["actions_switched_to_continuation"],
        ),
    )
    feature_name = selected_candidate["feature_set"]
    width = int(selected_candidate["feature_count"])
    l2 = float(selected_candidate["l2"])
    threshold = float(selected_candidate["validation"]["threshold"])
    packed, mean, std = fitted[(feature_name, l2)]

    probabilities_by_date = {
        date: predict_logistic(
            np.stack([record.features[:width] for record in records]), packed, mean, std
        )
        for date, records in by_date.items()
    }

    # Episode sizes for dependency-aware CIs.  This second pass reads only IDs,
    # dates, ranks, and action cardinality; none are classifier inputs.
    episode_sizes = defaultdict(lambda: defaultdict(int))
    with gzip.open(args.holdout, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if len(row.get("action", [])) == 1:
                rank = int(row.get("team_rank_aug4", 9999))
                episode = str(row["episode_id"])
                episode_sizes["broad"][episode] += 1
                if rank <= 20:
                    episode_sizes["hard_top20"][episode] += 1

    validation = scope_report(
        "Aug-5 validation (used for model/threshold selection)",
        "2026-08-05",
        summaries["2026-08-05"],
        by_date["2026-08-05"],
        probabilities_by_date["2026-08-05"],
        threshold,
    )
    broad_test = scope_report(
        "frozen Aug-6 rank1-100 test",
        "2026-08-06",
        summaries["2026-08-06"],
        by_date["2026-08-06"],
        probabilities_by_date["2026-08-06"],
        threshold,
        episode_sizes["broad"],
    )

    hard_records = [record for record in by_date["2026-08-06"] if record.rank <= 20]
    hard_probabilities = probabilities_by_date["2026-08-06"][
        np.asarray([record.rank <= 20 for record in by_date["2026-08-06"]], dtype=bool)
    ]
    hard_summary = summaries["2026-08-06|rank1_20"]
    hard_test = scope_report(
        "frozen Aug-6 rank1-20 hard test",
        "2026-08-06",
        hard_summary,
        hard_records,
        hard_probabilities,
        threshold,
        episode_sizes["hard_top20"],
    )

    always_continuation_validation_net = int(summaries["2026-08-05"]["fix"] - summaries["2026-08-05"]["harm"])
    hard_ci = hard_test["gate_uplift_vs_a2_episode_cluster_bootstrap_95"]
    broad_ci = broad_test["gate_uplift_vs_a2_episode_cluster_bootstrap_95"]
    broad_vs_continuation_ci = broad_test[
        "gate_uplift_vs_continuation_episode_cluster_bootstrap_95"
    ]
    hard_vs_continuation_ci = hard_test[
        "gate_uplift_vs_continuation_episode_cluster_bootstrap_95"
    ]
    # A feasibility pass requires prospective improvement on both frozen scopes,
    # positive lower CI on broad Aug-6, and a material gain over just always
    # selecting the continuation.  This deliberately conservative criterion is
    # fixed in code rather than chosen after seeing Aug-6.
    merits_gameplay = bool(
        broad_test["uplift_percentage_points_vs_a2"]["gate"] > 0.25
        and hard_test["uplift_percentage_points_vs_a2"]["gate"] > 0.0
        and broad_ci[0] > 0.0
        and broad_vs_continuation_ci[0] > 0.0
        and hard_vs_continuation_ci[0] > 0.0
    )

    report = {
        "schema_version": 1,
        "kind": "leakage_safe_temporal_context_gate_feasibility_screen",
        "verdict": "MERITS_PACKAGING_AND_GAMEPLAY" if merits_gameplay else "DO_NOT_PACKAGE_OR_GAMEPLAY",
        "scope_limit": (
            "elite winner-action imitation only; this cannot establish gameplay strength or causal action value"
        ),
        "protocol": {
            "fit_date": "2026-08-04",
            "selection_date": "2026-08-05",
            "frozen_test_date": "2026-08-06",
            "split_unit": "whole source episode-seat trajectory by date",
            "label": "on semantic top-1 disagreements: continuation fixes A2 vs continuation harms A2",
            "neither_matches": "excluded from fitting; retained in coverage and policy scoring",
            "inputs_allowed": (
                "public schema-3 observation features plus A2/continuation logits, values, and frozen embeddings"
            ),
            "metadata_excluded_from_features": [
                "source_date", "episode_id", "step", "team", "team_rank", "opponent",
                "opponent_archetype", "outcome", "reward",
            ],
            "classifier": "L2-regularized linear logistic gate; no hand-authored game rules",
            "selection": "feature family, L2, and coarse threshold selected only on Aug-5 net correct vs A2",
            "test_consumption": "Aug-6 evaluated only after selection was locked",
            "pristine_holdout_caveat": (
                "the gate never fit Aug-6 labels, but the supplied continuation checkpoint used Aug-6 "
                "as its training validation/checkpoint-selection set; Aug-6 is therefore not pristine "
                "for the policy pair"
            ),
            "multi_action_policy": "excluded from this feasibility screen",
        },
        "inputs": {
            "a2": {"path": str(args.a2), "sha256": sha256_file(args.a2)},
            "continuation": {"path": str(args.continuation), "sha256": sha256_file(args.continuation)},
            "train": {"path": str(args.train), "sha256": sha256_file(args.train)},
            "holdout": {"path": str(args.holdout), "sha256": sha256_file(args.holdout)},
            "hard_holdout": {
                "path": str(DEFAULT_DATA / "holdout_winners_aug6_rank1_20.jsonl.gz"),
                "sha256": sha256_file(DEFAULT_DATA / "holdout_winners_aug6_rank1_20.jsonl.gz"),
            },
        },
        "duplicate_rows_skipped": duplicates,
        "fit": {
            "decisive_disagreements": len(train_records),
            "fixes": sum(record.target == 1 for record in train_records),
            "harms": sum(record.target == 0 for record in train_records),
        },
        "candidate_count": len(candidates),
        "candidate_validation_results": candidates,
        "selected_candidate": selected_candidate,
        "always_continuation_validation_net_correct_vs_a2": always_continuation_validation_net,
        "validation": validation,
        "frozen_tests": {"broad_rank1_100": broad_test, "hard_rank1_20": hard_test},
        "promotion_rule": {
            "broad_gate_uplift_pp_gt": 0.25,
            "hard_gate_uplift_pp_gt": 0.0,
            "broad_episode_cluster_bootstrap_lower_gt": 0.0,
            "broad_gate_vs_continuation_episode_cluster_bootstrap_lower_gt": 0.0,
            "hard_gate_vs_continuation_episode_cluster_bootstrap_lower_gt": 0.0,
            "passed": merits_gameplay,
        },
        "interpretation": (
            "Package/gameplay only if the learned selector adds stable held-out value beyond always using "
            "the continuation.  The two-policy oracle is an unattainable upper bound and quantifies how "
            "little room this pair leaves for a gate."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "verdict": report["verdict"],
        "selected_candidate": selected_candidate,
        "broad_test": broad_test,
        "hard_test": hard_test,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
