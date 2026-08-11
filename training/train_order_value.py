#!/usr/bin/env python3
"""Fit only A2's value readout on disjoint terminal-outcome rollout shards."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from torch.nn import functional as F

from training.train_bc import PolicyNet, load_npz_weights
from training.train_public_value import (
    ValueRow,
    _shared_batch,
    binary_metrics,
    export_with_value_head,
    head_logits,
    sha256_file,
)


DEFAULT_BASE = ROOT / "artifacts" / "emergency_overall" / "extracted" / "alpha_0" / "policy_a2.npz"
DEFAULT_OUTPUT = ROOT / "artifacts" / "elite_policy_candidates" / "a2_order_public_value"


@dataclass(frozen=True)
class LoadedRows:
    rows: list[ValueRow]
    orders: tuple[str, ...]
    opponents: tuple[str, ...]
    policy_hashes: tuple[str, ...]
    paths: tuple[Path, ...]


def iter_order_rows(paths: Sequence[Path], *, feature_version: int) -> Iterator[tuple[ValueRow, str, str, str]]:
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                row = json.loads(line)
                features = row.get("features") or {}
                if int(features.get("feature_version", -1)) != feature_version:
                    raise ValueError(f"{path}:{line_number}: feature version mismatch")
                reward = float(row.get("terminal_reward", 99.0))
                if reward == 0.0:
                    continue
                if reward not in (-1.0, 1.0):
                    raise ValueError(f"{path}:{line_number}: invalid terminal reward")
                # Before this forced choice, firstPlayer is not latched in the
                # observation, so the two imposed-order labels are not a value
                # function of the encoded state. It is also never a search site.
                if bool(row.get("forced_order_decision", False)):
                    continue
                order = str(row.get("actual_order", ""))
                if order not in {"first", "second"}:
                    raise ValueError(f"{path}:{line_number}: actual order is not latched")
                seat = int(row.get("physical_seat", -1))
                if seat not in (0, 1):
                    raise ValueError(f"{path}:{line_number}: invalid physical seat")
                global_features = tuple(float(value) for value in features.get("global", ()))
                tokens = tuple(int(value) for value in features.get("tokens", ())) or (0,)
                if not global_features:
                    raise ValueError(f"{path}:{line_number}: empty global features")
                turn = int(round(global_features[0] * 100.0))
                yield (
                    ValueRow(
                        episode_id=str(row.get("episode_id", "")),
                        seat=seat,
                        label=float(reward > 0.0),
                        global_features=global_features,
                        tokens=tokens,
                        turn=turn,
                        step=int(row.get("step", -1)),
                    ),
                    order,
                    str(row.get("opponent_id", "unknown")),
                    str(row.get("policy_hash", "")).upper(),
                )


def load_rows(paths: Sequence[Path], *, feature_version: int, expected_policy_hash: str) -> LoadedRows:
    rows: list[ValueRow] = []
    orders: list[str] = []
    opponents: list[str] = []
    policy_hashes: list[str] = []
    unit_labels: dict[tuple[str, int], float] = {}
    for value_row, order, opponent, policy_hash in iter_order_rows(paths, feature_version=feature_version):
        if not value_row.episode_id:
            raise ValueError("empty episode id")
        unit = (value_row.episode_id, value_row.seat)
        previous = unit_labels.setdefault(unit, value_row.label)
        if previous != value_row.label:
            raise ValueError(f"trajectory {unit} has inconsistent outcomes")
        rows.append(value_row)
        orders.append(order)
        opponents.append(opponent)
        policy_hashes.append(policy_hash)
    if not rows:
        raise ValueError("no non-draw rollout rows")
    observed_hashes = set(policy_hashes)
    if observed_hashes != {expected_policy_hash.upper()}:
        raise ValueError(f"rollout/base policy mismatch: {sorted(observed_hashes)}")
    labels = set(unit_labels.values())
    if labels != {0.0, 1.0}:
        raise ValueError("each split must contain both winning and losing trajectories")
    if set(orders) != {"first", "second"}:
        raise ValueError("each split must contain both actual play orders")
    if {row.seat for row in rows} != {0, 1}:
        raise ValueError("each split must contain both physical seats")
    return LoadedRows(rows, tuple(orders), tuple(opponents), tuple(policy_hashes), tuple(paths))


def episode_turn_weights(rows: Sequence[ValueRow]) -> np.ndarray:
    """Give each episode unit equal mass, then each observed turn equal mass."""
    turn_rows = Counter((row.episode_id, row.seat, row.turn) for row in rows)
    unit_turns: dict[tuple[str, int], set[int]] = defaultdict(set)
    for row in rows:
        unit_turns[(row.episode_id, row.seat)].add(row.turn)
    weights = np.asarray(
        [
            1.0
            / (
                len(unit_turns[(row.episode_id, row.seat)])
                * turn_rows[(row.episode_id, row.seat, row.turn)]
            )
            for row in rows
        ],
        dtype=np.float32,
    )
    weights *= len(weights) / float(weights.sum())
    return weights


def episode_turn_weights_from(
    units: Sequence[tuple[str, int]], turns: Sequence[int]
) -> np.ndarray:
    turn_rows = Counter((unit, int(turn)) for unit, turn in zip(units, turns, strict=True))
    unit_turns: dict[tuple[str, int], set[int]] = defaultdict(set)
    for unit, turn in zip(units, turns, strict=True):
        unit_turns[unit].add(int(turn))
    weights = np.asarray(
        [
            1.0 / (len(unit_turns[unit]) * turn_rows[(unit, int(turn))])
            for unit, turn in zip(units, turns, strict=True)
        ],
        dtype=np.float32,
    )
    weights *= len(weights) / float(weights.sum())
    return weights


def materialize(
    model: PolicyNet,
    loaded: LoadedRows,
    *,
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[tuple[str, int]], np.ndarray, dict]:
    chunks: list[np.ndarray] = []
    for start in range(0, len(loaded.rows), batch_size):
        batch = loaded.rows[start : start + batch_size]
        with torch.no_grad():
            chunks.append(_shared_batch(model, batch, device).cpu().numpy().astype(np.float32))
    labels = np.asarray([row.label for row in loaded.rows], dtype=np.float32)
    turns = np.asarray([row.turn for row in loaded.rows], dtype=np.int16)
    steps = np.asarray([row.step for row in loaded.rows], dtype=np.int32)
    units = [(row.episode_id, row.seat) for row in loaded.rows]
    weights = episode_turn_weights(loaded.rows)
    unit_labels = {unit: labels[index] for index, unit in enumerate(units)}
    audit = {
        "rows": len(labels),
        "episodes": len({unit[0] for unit in units}),
        "trajectories": len(unit_labels),
        "win_trajectories": int(sum(value > 0 for value in unit_labels.values())),
        "loss_trajectories": int(sum(value == 0 for value in unit_labels.values())),
        "orders": dict(Counter(loaded.orders)),
        "physical_seats": dict(Counter(str(row.seat) for row in loaded.rows)),
        "opponents": dict(Counter(loaded.opponents)),
        "turn_range": [int(turns.min()), int(turns.max())],
        "episode_turn_weight_sum_range": _unit_weight_range(units, weights),
    }
    return np.concatenate(chunks), labels, turns, steps, units, weights, audit


def materialize_paths(
    model: PolicyNet,
    paths: Sequence[Path],
    *,
    feature_version: int,
    expected_policy_hash: str,
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[tuple[str, int]], np.ndarray, dict]:
    """Stream compact rows into shared vectors without retaining JSON feature objects."""
    chunks: list[np.ndarray] = []
    labels: list[float] = []
    turns: list[int] = []
    steps: list[int] = []
    units: list[tuple[str, int]] = []
    orders: list[str] = []
    opponents: list[str] = []
    seats: set[int] = set()
    policy_hashes: set[str] = set()
    unit_labels: dict[tuple[str, int], float] = {}
    batch: list[ValueRow] = []

    def flush() -> None:
        if not batch:
            return
        with torch.no_grad():
            chunks.append(_shared_batch(model, batch, device).cpu().numpy().astype(np.float32))
        batch.clear()

    for row, order, opponent, policy_hash in iter_order_rows(paths, feature_version=feature_version):
        if not row.episode_id:
            raise ValueError("empty episode id")
        unit = (row.episode_id, row.seat)
        previous = unit_labels.setdefault(unit, row.label)
        if previous != row.label:
            raise ValueError(f"trajectory {unit} has inconsistent outcomes")
        labels.append(row.label)
        turns.append(row.turn)
        steps.append(row.step)
        units.append(unit)
        orders.append(order)
        opponents.append(opponent)
        seats.add(row.seat)
        policy_hashes.add(policy_hash)
        batch.append(row)
        if len(batch) >= batch_size:
            flush()
    flush()
    if not chunks:
        raise ValueError("no non-draw rollout rows")
    if policy_hashes != {expected_policy_hash.upper()}:
        raise ValueError(f"rollout/base policy mismatch: {sorted(policy_hashes)}")
    if set(unit_labels.values()) != {0.0, 1.0}:
        raise ValueError("each split must contain both winning and losing trajectories")
    if set(orders) != {"first", "second"}:
        raise ValueError("each split must contain both actual play orders")
    if seats != {0, 1}:
        raise ValueError("each split must contain both physical seats")
    label_array = np.asarray(labels, dtype=np.float32)
    turn_array = np.asarray(turns, dtype=np.int16)
    step_array = np.asarray(steps, dtype=np.int32)
    weights = episode_turn_weights_from(units, turn_array)
    audit = {
        "rows": len(label_array),
        "episodes": len({unit[0] for unit in units}),
        "trajectories": len(unit_labels),
        "win_trajectories": int(sum(value > 0 for value in unit_labels.values())),
        "loss_trajectories": int(sum(value == 0 for value in unit_labels.values())),
        "orders": dict(Counter(orders)),
        "physical_seats": dict(Counter(str(unit[1]) for unit in units)),
        "opponents": dict(Counter(opponents)),
        "turn_range": [int(turn_array.min()), int(turn_array.max())],
        "episode_turn_weight_sum_range": _unit_weight_range(units, weights),
    }
    return np.concatenate(chunks), label_array, turn_array, step_array, units, weights, audit


def _unit_weight_range(units: Sequence[tuple[str, int]], weights: np.ndarray) -> list[float]:
    totals: dict[tuple[str, int], float] = defaultdict(float)
    for unit, weight in zip(units, weights, strict=True):
        totals[unit] += float(weight)
    return [min(totals.values()), max(totals.values())]


def _weighted_auc(labels: np.ndarray, probabilities: np.ndarray, weights: np.ndarray) -> float | None:
    positive_weight = float(weights[labels > 0.5].sum())
    negative_weight = float(weights[labels < 0.5].sum())
    if positive_weight == 0.0 or negative_weight == 0.0:
        return None
    order = np.argsort(probabilities, kind="mergesort")
    labels = labels[order]
    probabilities = probabilities[order]
    weights = weights[order]
    numerator = 0.0
    negative_before = 0.0
    start = 0
    while start < len(labels):
        end = start + 1
        while end < len(labels) and probabilities[end] == probabilities[start]:
            end += 1
        tie_positive = float(weights[start:end][labels[start:end] > 0.5].sum())
        tie_negative = float(weights[start:end][labels[start:end] < 0.5].sum())
        numerator += tie_positive * (negative_before + 0.5 * tie_negative)
        negative_before += tie_negative
        start = end
    return numerator / (positive_weight * negative_weight)


def weighted_metrics(labels: np.ndarray, logits: np.ndarray, weights: np.ndarray) -> dict:
    if len(labels) == 0:
        return {"rows": 0}
    weights = weights.astype(np.float64)
    weights /= weights.sum()
    probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
    bce = np.logaddexp(0.0, logits) - labels * logits
    bins = np.minimum((probabilities * 10).astype(np.int64), 9)
    ece = 0.0
    for index in range(10):
        mask = bins == index
        if mask.any():
            bin_weight = float(weights[mask].sum())
            confidence = float(np.average(probabilities[mask], weights=weights[mask]))
            outcome = float(np.average(labels[mask], weights=weights[mask]))
            ece += bin_weight * abs(confidence - outcome)
    return {
        "rows": len(labels),
        "positive_rate": float(np.average(labels, weights=weights)),
        "bce": float(np.average(bce, weights=weights)),
        "brier": float(np.average(np.square(probabilities - labels), weights=weights)),
        "accuracy": float(np.average((probabilities >= 0.5) == (labels > 0.5), weights=weights)),
        "auc": _weighted_auc(labels, probabilities, weights),
        "ece_10": ece,
    }


def evaluate(
    labels: np.ndarray,
    logits: np.ndarray,
    turns: np.ndarray,
    steps: np.ndarray,
    units: Sequence[tuple[str, int]],
    weights: np.ndarray,
) -> dict:
    first: dict[tuple[str, int], int] = {}
    for index, unit in enumerate(units):
        if unit not in first or steps[index] < steps[first[unit]]:
            first[unit] = index
    first_indices = np.asarray(sorted(first.values()), dtype=np.int64)
    result = {
        "decision_weighted": binary_metrics(labels, logits),
        "episode_turn_balanced": weighted_metrics(labels, logits, weights),
        "first_decision_per_trajectory": binary_metrics(labels[first_indices], logits[first_indices]),
    }
    for name, mask in {
        "turn_0_2": turns <= 2,
        "turn_3_5": (turns >= 3) & (turns <= 5),
        "turn_6_plus": turns >= 6,
    }.items():
        result[name] = weighted_metrics(labels[mask], logits[mask], weights[mask])
    return result


def train(args: argparse.Namespace) -> dict:
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    base = Path(args.base).resolve()
    expected_policy_hash = sha256_file(base).upper()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    split_paths = {
        name: tuple(Path(path).resolve() for path in getattr(args, name))
        for name in ("train", "validation", "holdout")
    }
    all_paths = [path for paths in split_paths.values() for path in paths]
    if len(set(all_paths)) != len(all_paths):
        raise ValueError("rollout shards must belong to exactly one split")
    with np.load(base, allow_pickle=False) as arrays:
        feature_version = int(np.asarray(arrays.get("model_schema_version", 1)).item())
    if feature_version != 2:
        raise ValueError("order rollout value fitting is locked to authentic A2 schema 2")
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")
    model = PolicyNet(feature_version).to(device)
    load_npz_weights(model, base)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad = False

    datasets = {
        name: materialize_paths(
            model,
            paths,
            feature_version=feature_version,
            expected_policy_hash=expected_policy_hash,
            device=device,
            batch_size=args.encode_batch_size,
        )
        for name, paths in split_paths.items()
    }
    unit_sets = {name: set(values[4]) for name, values in datasets.items()}
    for left, right in (("train", "validation"), ("train", "holdout"), ("validation", "holdout")):
        overlap = unit_sets[left] & unit_sets[right]
        if overlap:
            raise ValueError(f"trajectory leakage between {left} and {right}: {next(iter(overlap))}")
    initial_weight = model.value.weight.detach().cpu().numpy().reshape(-1).astype(np.float32)
    initial_bias = float(model.value.bias.detach().cpu().item())
    before = {
        name: evaluate(
            values[1], head_logits(values[0], initial_weight, initial_bias),
            values[2], values[3], values[4], values[5],
        )
        for name, values in datasets.items()
    }

    train_x = torch.from_numpy(datasets["train"][0])
    train_y = torch.from_numpy(datasets["train"][1])
    train_weights = torch.from_numpy(datasets["train"][5])
    validation = datasets["validation"]
    linear = torch.nn.Linear(train_x.shape[1], 1).to(device)
    with torch.no_grad():
        linear.weight.copy_(torch.from_numpy(initial_weight.reshape(1, -1)).to(device))
        linear.bias.fill_(initial_bias)
    optimizer = torch.optim.AdamW(linear.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    generator = np.random.default_rng(args.seed)
    best = {
        "epoch": 0,
        "bce": before["validation"]["episode_turn_balanced"]["bce"],
        "weight": initial_weight.copy(),
        "bias": initial_bias,
    }
    history = []
    for epoch in range(1, args.epochs + 1):
        order = generator.permutation(len(train_y))
        total_loss = 0.0
        total_weight = 0.0
        linear.train()
        for start in range(0, len(order), args.batch_size):
            indices = order[start : start + args.batch_size]
            x = train_x[indices].to(device)
            y = train_y[indices].to(device)
            weight = train_weights[indices].to(device)
            optimizer.zero_grad()
            losses = F.binary_cross_entropy_with_logits(linear(x).squeeze(1), y, reduction="none")
            loss = (losses * weight).sum() / weight.sum().clamp_min(1e-8)
            loss.backward()
            optimizer.step()
            total_loss += float((losses * weight).sum().item())
            total_weight += float(weight.sum().item())
        weight = linear.weight.detach().cpu().numpy().reshape(-1).astype(np.float32)
        bias = float(linear.bias.detach().cpu().item())
        val_logits = head_logits(validation[0], weight, bias)
        val_metrics = evaluate(
            validation[1], val_logits, validation[2], validation[3], validation[4], validation[5]
        )
        history.append({
            "epoch": epoch,
            "train_weighted_bce": total_loss / total_weight,
            "validation": val_metrics,
        })
        score = val_metrics["episode_turn_balanced"]["bce"]
        if score < best["bce"]:
            best = {"epoch": epoch, "bce": score, "weight": weight.copy(), "bias": bias}

    output_model = output_dir / "policy_weights.npz"
    export_with_value_head(base, output_model, best["weight"], best["bias"])
    after = {
        name: evaluate(
            values[1], head_logits(values[0], best["weight"], best["bias"]),
            values[2], values[3], values[4], values[5],
        )
        for name, values in datasets.items()
    }
    with np.load(base, allow_pickle=False) as old, np.load(output_model, allow_pickle=False) as new:
        changed = [name for name in old.files if not np.array_equal(old[name], new[name])]
    if set(changed) - {"value_w", "value_b"}:
        raise AssertionError(f"value-only export changed policy arrays: {changed}")
    result = {
        "status": "complete",
        "base": str(base),
        "base_sha256": expected_policy_hash,
        "output_model": str(output_model),
        "output_sha256": sha256_file(output_model).upper(),
        "feature_version": feature_version,
        "device": str(device),
        "seed": args.seed,
        "epochs": args.epochs,
        "best_epoch": best["epoch"],
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "weighting": "equal episode mass; equal turn mass within episode; equal row mass within turn",
        "excluded_rows": "draw outcomes and forced IS_FIRST decisions whose order is not yet encoded",
        "changed_arrays": changed,
        "inputs": {
            name: [{"path": str(path), "sha256": sha256_file(path)} for path in paths]
            for name, paths in split_paths.items()
        },
        "data_audit": {name: values[6] for name, values in datasets.items()},
        "trajectory_overlap": {"train_validation": 0, "train_holdout": 0, "validation_holdout": 0},
        "before": before,
        "after": after,
        "history": history,
    }
    (output_dir / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=str(DEFAULT_BASE))
    parser.add_argument("--train", nargs="+", required=True)
    parser.add_argument("--validation", nargs="+", required=True)
    parser.add_argument("--holdout", nargs="+", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--encode-batch-size", type=int, default=4096)
    parser.add_argument("--learning-rate", type=float, default=2e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument("--cpu", action="store_true")
    args = parser.parse_args()
    if args.epochs <= 0 or args.batch_size <= 0 or args.encode_batch_size <= 0:
        raise ValueError("epochs and batch sizes must be positive")
    result = train(args)
    print(json.dumps({
        "status": result["status"],
        "output_model": result["output_model"],
        "output_sha256": result["output_sha256"],
        "best_epoch": result["best_epoch"],
        "data_audit": result["data_audit"],
        "holdout_before": result["before"]["holdout"],
        "holdout_after": result["after"]["holdout"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
