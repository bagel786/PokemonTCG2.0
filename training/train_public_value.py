#!/usr/bin/env python3
"""Fit only the frozen policy's value readout on exact-deck win/loss games.

The policy, count head, embeddings, and shared representation are never updated.
Training, validation, and final holdout are separate date shards, and every input
row must be an observation for the exact requested deck.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
from torch.nn import functional as F

from training.train_bc import PolicyNet, load_npz_weights


DEFAULT_BASE = ROOT / "artifacts" / "elite_policy_candidates" / "a2_schema3_zero_init.npz"
DEFAULT_DECK = ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv"
DEFAULT_TRAIN = ROOT / "data" / "grim_daily_v3" / "shards" / "2026-08-04.jsonl.gz"
DEFAULT_VALIDATION = ROOT / "data" / "grim_daily_v3" / "shards" / "2026-08-05.jsonl.gz"
DEFAULT_HOLDOUT = ROOT / "data" / "grim_daily_v3" / "shards" / "2026-08-06.jsonl.gz"
DEFAULT_OUTPUT = ROOT / "artifacts" / "elite_policy_candidates" / "a2_public_value"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_deck(path: Path) -> tuple[int, ...]:
    cards = tuple(sorted(int(line.strip()) for line in path.read_text().splitlines() if line.strip()))
    if len(cards) != 60:
        raise ValueError(f"exact deck must contain 60 cards, found {len(cards)}")
    return cards


@dataclass(frozen=True)
class ValueRow:
    episode_id: str
    seat: int
    label: float
    global_features: tuple[float, ...]
    tokens: tuple[int, ...]
    turn: int
    step: int


def iter_value_rows(
    paths: Sequence[Path],
    *,
    exact_deck: tuple[int, ...],
    feature_version: int,
) -> Iterator[ValueRow]:
    """Yield complete exact-deck trajectories without exposing replay metadata to the net."""
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                row = json.loads(line)
                if tuple(sorted(int(card) for card in row.get("deck", ()))) != exact_deck:
                    continue
                reward = float(row.get("reward", 0.0))
                if reward == 0.0:
                    continue
                if reward not in (-1.0, 1.0):
                    raise ValueError(f"{path}:{line_number}: invalid terminal reward {reward}")
                features = row.get("features") or {}
                if int(features.get("feature_version", -1)) != feature_version:
                    raise ValueError(f"{path}:{line_number}: feature version mismatch")
                global_features = tuple(float(value) for value in features.get("global", ()))
                tokens = tuple(int(value) for value in features.get("tokens", ())) or (0,)
                observation = row.get("observation") or {}
                current = observation.get("current") or {}
                seat = int(row.get("seat", current.get("yourIndex", -1)))
                if seat not in (0, 1) or int(current.get("yourIndex", seat)) != seat:
                    raise ValueError(f"{path}:{line_number}: row is not the hero-seat observation")
                yield ValueRow(
                    episode_id=str(row.get("episode_id")),
                    seat=seat,
                    label=float(reward > 0.0),
                    global_features=global_features,
                    tokens=tokens,
                    turn=int(row.get("turn", current.get("turn", -1))),
                    step=int(row.get("step", observation.get("step", -1))),
                )


def _shared_batch(model: PolicyNet, rows: Sequence[ValueRow], device: torch.device) -> torch.Tensor:
    token_values: list[int] = []
    offsets: list[int] = []
    for row in rows:
        offsets.append(len(token_values))
        token_values.extend(row.tokens)
    tokens = torch.tensor(token_values, dtype=torch.long, device=device)
    offset_tensor = torch.tensor(offsets, dtype=torch.long, device=device)
    globals_ = torch.tensor([row.global_features for row in rows], dtype=torch.float32, device=device)
    state = model.state_embedding(tokens, offset_tensor)
    ends = torch.cat(
        [offset_tensor[1:], torch.tensor([len(tokens)], dtype=torch.long, device=device)]
    )
    state = state / (ends - offset_tensor).clamp_min(1).sqrt().unsqueeze(1)
    global_vector = torch.tanh(model.global_linear(globals_))
    return torch.cat([state, global_vector], dim=-1)


def materialize_shared(
    model: PolicyNet,
    paths: Sequence[Path],
    *,
    exact_deck: tuple[int, ...],
    feature_version: int,
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[tuple[str, int]], dict]:
    chunks: list[np.ndarray] = []
    labels: list[np.ndarray] = []
    turns: list[np.ndarray] = []
    steps: list[np.ndarray] = []
    units: list[tuple[str, int]] = []
    unit_labels: dict[tuple[str, int], float] = {}
    episodes: set[str] = set()
    batch: list[ValueRow] = []
    counts = Counter()

    def flush() -> None:
        if not batch:
            return
        with torch.no_grad():
            chunks.append(_shared_batch(model, batch, device).cpu().numpy().astype(np.float32))
        labels.append(np.asarray([row.label for row in batch], dtype=np.float32))
        turns.append(np.asarray([row.turn for row in batch], dtype=np.int16))
        steps.append(np.asarray([row.step for row in batch], dtype=np.int32))
        batch.clear()

    for row in iter_value_rows(paths, exact_deck=exact_deck, feature_version=feature_version):
        unit = (row.episode_id, row.seat)
        previous = unit_labels.setdefault(unit, row.label)
        if previous != row.label:
            raise ValueError(f"trajectory {unit} has inconsistent outcome labels")
        episodes.add(row.episode_id)
        units.append(unit)
        counts["win_rows" if row.label else "loss_rows"] += 1
        batch.append(row)
        if len(batch) >= batch_size:
            flush()
    flush()
    if not chunks:
        raise ValueError("no exact-deck win/loss rows were admitted")
    audit = {
        "rows": int(sum(len(chunk) for chunk in chunks)),
        "episodes": len(episodes),
        "trajectories": len(unit_labels),
        "win_trajectories": sum(label > 0 for label in unit_labels.values()),
        "loss_trajectories": sum(label == 0 for label in unit_labels.values()),
        **dict(counts),
    }
    if not audit["win_trajectories"] or not audit["loss_trajectories"]:
        raise ValueError(
            "value fitting requires both winning and losing trajectories; "
            f"admitted wins={audit['win_trajectories']} losses={audit['loss_trajectories']}"
        )
    return (
        np.concatenate(chunks),
        np.concatenate(labels),
        np.concatenate(turns),
        np.concatenate(steps),
        units,
        audit,
    )


def _auc(labels: np.ndarray, probabilities: np.ndarray) -> float | None:
    positives = int(labels.sum())
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    order = np.argsort(probabilities, kind="mergesort")
    sorted_probabilities = probabilities[order]
    ranks = np.empty(len(labels), dtype=np.float64)
    start = 0
    while start < len(labels):
        end = start + 1
        while end < len(labels) and sorted_probabilities[end] == sorted_probabilities[start]:
            end += 1
        ranks[order[start:end]] = 0.5 * (start + 1 + end)
        start = end
    rank_sum = float(ranks[labels > 0.5].sum())
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def binary_metrics(labels: np.ndarray, logits: np.ndarray) -> dict:
    if len(labels) == 0:
        return {"rows": 0}
    probabilities = 1.0 / (1.0 + np.exp(-np.clip(logits, -40.0, 40.0)))
    bce = np.logaddexp(0.0, logits) - labels * logits
    bins = np.minimum((probabilities * 10).astype(np.int64), 9)
    ece = 0.0
    for index in range(10):
        mask = bins == index
        if mask.any():
            ece += float(mask.mean()) * abs(float(probabilities[mask].mean() - labels[mask].mean()))
    return {
        "rows": len(labels),
        "positive_rate": float(labels.mean()),
        "bce": float(bce.mean()),
        "brier": float(np.square(probabilities - labels).mean()),
        "accuracy": float(((probabilities >= 0.5) == (labels > 0.5)).mean()),
        "auc": _auc(labels, probabilities),
        "ece_10": ece,
        "mean_probability_win": float(probabilities[labels > 0.5].mean()) if labels.any() else None,
        "mean_probability_loss": float(probabilities[labels < 0.5].mean()) if (labels < 0.5).any() else None,
    }


def evaluate_slices(
    labels: np.ndarray,
    logits: np.ndarray,
    turns: np.ndarray,
    steps: np.ndarray,
    units: Sequence[tuple[str, int]],
) -> dict:
    masks = {
        "all_decisions": np.ones(len(labels), dtype=bool),
        "turn_0_2": (turns >= 0) & (turns <= 2),
        "turn_3_5": (turns >= 3) & (turns <= 5),
        "turn_6_plus": turns >= 6,
    }
    result = {name: binary_metrics(labels[mask], logits[mask]) for name, mask in masks.items()}
    first_indices: dict[tuple[str, int], int] = {}
    for index, unit in enumerate(units):
        if unit not in first_indices or steps[index] < steps[first_indices[unit]]:
            first_indices[unit] = index
    selected = np.asarray(sorted(first_indices.values()), dtype=np.int64)
    result["first_decision_per_trajectory"] = binary_metrics(labels[selected], logits[selected])
    return result


def head_logits(shared: np.ndarray, weight: np.ndarray, bias: float) -> np.ndarray:
    return shared @ weight.reshape(-1) + float(bias)


def export_with_value_head(base: Path, output: Path, weight: np.ndarray, bias: float) -> None:
    with np.load(base, allow_pickle=False) as arrays:
        payload = {name: np.asarray(arrays[name]) for name in arrays.files}
    expected_shape = payload["value_w"].shape
    payload["value_w"] = np.asarray(weight, dtype=payload["value_w"].dtype).reshape(expected_shape)
    payload["value_b"] = np.asarray([bias], dtype=payload["value_b"].dtype)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output, **payload)


def train(args: argparse.Namespace) -> dict:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    base = Path(args.base).resolve()
    deck_path = Path(args.deck).resolve()
    train_paths = [Path(path).resolve() for path in args.train]
    validation_paths = [Path(path).resolve() for path in args.validation]
    holdout_paths = [Path(path).resolve() for path in args.holdout]
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    exact_deck = load_deck(deck_path)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.cpu else "cpu")

    with np.load(base, allow_pickle=False) as arrays:
        feature_version = int(np.asarray(arrays.get("model_schema_version", 1)).item())
    if feature_version < 2:
        raise ValueError("public value trainer requires schema 2 or newer")
    model = PolicyNet(feature_version).to(device)
    load_npz_weights(model, base)
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad = False

    datasets = {}
    for name, paths in (
        ("train", train_paths),
        ("validation", validation_paths),
        ("holdout", holdout_paths),
    ):
        datasets[name] = materialize_shared(
            model,
            paths,
            exact_deck=exact_deck,
            feature_version=feature_version,
            device=device,
            batch_size=args.encode_batch_size,
        )

    episode_sets = {
        name: {episode_id for episode_id, _seat in values[4]}
        for name, values in datasets.items()
    }
    for left, right in (("train", "validation"), ("train", "holdout"), ("validation", "holdout")):
        overlap = episode_sets[left] & episode_sets[right]
        if overlap:
            raise ValueError(f"episode leakage between {left} and {right}: {next(iter(overlap))}")

    initial_weight = model.value.weight.detach().cpu().numpy().reshape(-1).astype(np.float32)
    initial_bias = float(model.value.bias.detach().cpu().item())
    before = {
        name: evaluate_slices(
            values[1],
            head_logits(values[0], initial_weight, initial_bias),
            values[2],
            values[3],
            values[4],
        )
        for name, values in datasets.items()
    }

    train_shared, train_labels = datasets["train"][:2]
    validation_shared, validation_labels = datasets["validation"][:2]
    linear = torch.nn.Linear(train_shared.shape[1], 1).to(device)
    with torch.no_grad():
        linear.weight.copy_(torch.from_numpy(initial_weight.reshape(1, -1)).to(device))
        linear.bias.fill_(initial_bias)
    optimizer = torch.optim.AdamW(linear.parameters(), lr=args.learning_rate, weight_decay=args.weight_decay)
    generator = np.random.default_rng(args.seed)
    best = {
        "epoch": 0,
        "bce": before["validation"]["all_decisions"]["bce"],
        "weight": initial_weight.copy(),
        "bias": initial_bias,
    }
    history = []
    train_x = torch.from_numpy(train_shared)
    train_y = torch.from_numpy(train_labels)
    for epoch in range(1, args.epochs + 1):
        linear.train()
        order = generator.permutation(len(train_labels))
        total_loss = 0.0
        total_rows = 0
        for start in range(0, len(order), args.batch_size):
            indices = order[start : start + args.batch_size]
            x = train_x[indices].to(device)
            y = train_y[indices].to(device)
            optimizer.zero_grad()
            logits = linear(x).squeeze(1)
            loss = F.binary_cross_entropy_with_logits(logits, y)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.item()) * len(indices)
            total_rows += len(indices)
        weight = linear.weight.detach().cpu().numpy().reshape(-1).astype(np.float32)
        bias = float(linear.bias.detach().cpu().item())
        validation_logits = head_logits(validation_shared, weight, bias)
        validation_metrics = binary_metrics(validation_labels, validation_logits)
        history.append(
            {
                "epoch": epoch,
                "train_bce": total_loss / max(1, total_rows),
                "validation": validation_metrics,
            }
        )
        if validation_metrics["bce"] < best["bce"]:
            best = {"epoch": epoch, "bce": validation_metrics["bce"], "weight": weight.copy(), "bias": bias}

    output_model = output_dir / "policy_weights.npz"
    export_with_value_head(base, output_model, best["weight"], best["bias"])
    after = {
        name: evaluate_slices(
            values[1],
            head_logits(values[0], best["weight"], best["bias"]),
            values[2],
            values[3],
            values[4],
        )
        for name, values in datasets.items()
    }
    with np.load(base, allow_pickle=False) as old, np.load(output_model, allow_pickle=False) as new:
        changed = [
            name for name in old.files
            if not np.array_equal(np.asarray(old[name]), np.asarray(new[name]))
        ]
    if set(changed) - {"value_w", "value_b"}:
        raise AssertionError(f"value-only export changed policy arrays: {changed}")

    result = {
        "status": "complete",
        "base": str(base),
        "base_sha256": sha256_file(base),
        "output_model": str(output_model),
        "output_sha256": sha256_file(output_model),
        "deck": str(deck_path),
        "deck_sha256": sha256_file(deck_path),
        "feature_version": feature_version,
        "device": str(device),
        "seed": args.seed,
        "epochs": args.epochs,
        "best_epoch": best["epoch"],
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "changed_arrays": changed,
        "inputs": {
            name: [{"path": str(path), "sha256": sha256_file(path)} for path in paths]
            for name, paths in (
                ("train", train_paths),
                ("validation", validation_paths),
                ("holdout", holdout_paths),
            )
        },
        "data_audit": {name: values[5] for name, values in datasets.items()},
        "episode_overlap": {"train_validation": 0, "train_holdout": 0, "validation_holdout": 0},
        "before": before,
        "after": after,
        "history": history,
    }
    (output_dir / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=str(DEFAULT_BASE))
    parser.add_argument("--deck", default=str(DEFAULT_DECK))
    parser.add_argument("--train", nargs="+", default=[str(DEFAULT_TRAIN)])
    parser.add_argument("--validation", nargs="+", default=[str(DEFAULT_VALIDATION)])
    parser.add_argument("--holdout", nargs="+", default=[str(DEFAULT_HOLDOUT)])
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--encode-batch-size", type=int, default=2048)
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
