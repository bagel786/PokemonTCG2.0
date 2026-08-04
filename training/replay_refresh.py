#!/usr/bin/env python3
"""Guarded elite-replay refresh experiment for the deployed 5k policy.

This runner is deliberately experiment-only: it trains NPZ checkpoints and
writes evaluation reports, but it has no packaging or submission capability.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import tarfile
import time
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "freshstart" / "submission_template"))
if (ROOT / "vendor" / "cg").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch
from torch.nn import functional as F

from ptcg_ai.features import MAX_SELECT_COUNT
from training.train_bc import (
    PolicyNet,
    collate,
    export_npz,
    load_npz_weights,
    masked_count_loss,
    move,
    policy_loss,
    split_bucket,
)


EXPECTED_ARCHIVE_SHA256 = "3ecb0bbf119e23c31905e39e19eca8f6145104aaeffc0a5675d2fe03855bb458"
EXPECTED_CONTROL_SHA256 = "d842f85abfc44af9f41979f91795e22c92c179b62e04d5a0a2f9c734e70af1c3"
EXPECTED_DECK_SHA256 = "92b92bac9f9163ecff933b3dc39294d2cc154c8684f3c8497877661419ebc59d"
DEFAULT_TRAINABLE_MODULES = ("option_linear", "score", "count", "value")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_archive_member(path: str | Path, member: str) -> str:
    digest = hashlib.sha256()
    with tarfile.open(path, "r:gz") as archive:
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ValueError(f"archive member is not a regular file: {member}")
        for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_team_bucket(team: str) -> int:
    return zlib.crc32(str(team).encode("utf-8")) % 10


def row_key(row: dict) -> tuple[str, int, int]:
    return str(row.get("episode_id", "")), int(row.get("seat", -1)), int(row.get("step", -1))


def auto_device(requested: str = "auto") -> torch.device:
    requested = requested.lower()
    if requested != "auto":
        if requested == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        if requested == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            raise RuntimeError("MPS was requested but is unavailable")
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _matches(row: dict, required_card: int, feature_version: int) -> bool:
    if required_card and required_card not in row.get("deck", []):
        return False
    return not feature_version or int(row.get("features", {}).get("feature_version", 1)) == feature_version


def _jsonl_rows(path: str | Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def temporal_episode_ids(directory: str | Path) -> set[str]:
    result = {path.stem for path in Path(directory).glob("*.json")}
    if not result:
        raise ValueError(f"no temporal replay files found in {directory}")
    return result


def classify_fresh_row(row: dict, manifest: dict) -> str:
    explicit = row.get("split")
    if explicit is not None:
        mapping = {
            "train": "train",
            "validation": "internal_validation",
            "holdout": "team_holdout",
            "unseen_team": "team_holdout",
            "temporal": "temporal",
        }
        if explicit not in mapping:
            raise ValueError(f"invalid explicit replay split: {explicit!r}")
        return mapping[explicit]
    episode = str(row.get("episode_id", ""))
    if episode in manifest["temporal_episode_ids"]:
        return "temporal"
    if str(row.get("team", "")) in manifest["heldout_teams"]:
        return "team_holdout"
    if split_bucket(episode) == 0:
        return "internal_validation"
    return "train"


def build_split_manifest(
    fresh_path: str | Path,
    rehearsal_path: str | Path,
    temporal_dir: str | Path,
    required_card: int = 648,
    feature_version: int = 2,
) -> dict:
    """Scan source shards and return a deterministic, auditable split manifest."""
    temporal = temporal_episode_ids(temporal_dir)
    heldout = set()
    seen = set()
    duplicates = 0
    for row in _jsonl_rows(fresh_path):
        if not _matches(row, required_card, feature_version):
            continue
        key = row_key(row)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        if str(row.get("episode_id", "")) not in temporal and stable_team_bucket(row.get("team", "")) == 0:
            heldout.add(str(row.get("team", "")))

    manifest = {
        "version": 1,
        "rules": {
            "temporal": "episode id is a filename stem in the temporal replay directory",
            "team_holdout": "non-temporal team with crc32(utf8(team)) % 10 == 0",
            "internal_validation": "non-temporal, non-heldout episode with crc32(utf8(episode_id)) % 10 == 0",
            "train": "all remaining matching fresh records",
            "rehearsal": "matching rehearsal records excluding every heldout team",
            "deduplication_key": ["episode_id", "seat", "step"],
            "precedence": ["temporal", "team_holdout", "internal_validation", "train"],
        },
        "required_card": required_card,
        "feature_version": feature_version,
        "temporal_episode_ids": sorted(temporal),
        "heldout_teams": sorted(heldout),
        "counts": defaultdict(int),
        "episodes": defaultdict(set),
        "duplicate_rows_skipped": {"fresh": duplicates, "rehearsal": 0},
    }

    seen.clear()
    for row in _jsonl_rows(fresh_path):
        if not _matches(row, required_card, feature_version):
            continue
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        split = classify_fresh_row(row, manifest)
        manifest["counts"][split] += 1
        manifest["episodes"][split].add(str(row.get("episode_id", "")))

    seen.clear()
    for row in _jsonl_rows(rehearsal_path):
        if not _matches(row, required_card, feature_version):
            continue
        if str(row.get("team", "")) in heldout:
            manifest["counts"]["rehearsal_heldout_excluded"] += 1
            continue
        key = row_key(row)
        if key in seen:
            manifest["duplicate_rows_skipped"]["rehearsal"] += 1
            continue
        seen.add(key)
        manifest["counts"]["rehearsal"] += 1
        manifest["episodes"]["rehearsal"].add(str(row.get("episode_id", "")))

    manifest["counts"] = dict(sorted(manifest["counts"].items()))
    manifest["episodes"] = {name: len(values) for name, values in sorted(manifest["episodes"].items())}
    return manifest


def load_team_weights(path: str | Path | None) -> tuple[dict[str, float], list[str]]:
    if not path:
        return {}, []
    names = [line.strip() for line in Path(path).read_text().splitlines() if line.strip()]
    weights = {
        name: 1.5 if rank <= 20 else 1.2 if rank <= 50 else 1.0
        for rank, name in enumerate(names, 1)
    }
    return weights, names


def iter_split_rows(
    path: str | Path,
    manifest: dict,
    split: str,
    source: str = "fresh",
    team_weights: dict[str, float] | None = None,
) -> Iterator[dict]:
    seen = set()
    heldout = set(manifest["heldout_teams"])
    for row in _jsonl_rows(path):
        if not _matches(row, manifest["required_card"], manifest["feature_version"]):
            continue
        if source == "fresh":
            if classify_fresh_row(row, manifest) != split:
                continue
        elif source == "rehearsal":
            if split != "train" or str(row.get("team", "")) in heldout:
                continue
        else:
            raise ValueError(f"unknown source: {source}")
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        row["sample_weight"] = float((team_weights or {}).get(row.get("team"), 1.0))
        row["sample_source"] = source
        yield row


def buffered_shuffle(rows: Iterable[dict], rng: random.Random, size: int = 20_000) -> Iterator[dict]:
    buffer = []
    for row in rows:
        buffer.append(row)
        if len(buffer) >= size:
            rng.shuffle(buffer)
            yield from buffer
            buffer.clear()
    rng.shuffle(buffer)
    yield from buffer


def mixed_row_batches(
    fresh_factory: Callable[[], Iterable[dict]],
    rehearsal_factory: Callable[[], Iterable[dict]],
    batch_size: int,
    fresh_weight: float,
    seed: int,
    max_records: int = 0,
    shuffle_buffer: int = 20_000,
) -> Iterator[list[dict]]:
    """Yield batches with a fixed per-batch source mix until fresh rows are exhausted."""
    if not 0.0 < fresh_weight < 1.0:
        raise ValueError("fresh_weight must be strictly between zero and one")
    if batch_size < 2:
        raise ValueError("batch_size must be at least two")
    rng = random.Random(seed)
    fresh = iter(buffered_shuffle(fresh_factory(), rng, shuffle_buffer))
    rehearsal_cycle = 0
    rehearsal = iter(buffered_shuffle(rehearsal_factory(), random.Random(seed + 10_000), shuffle_buffer))
    emitted = 0
    while not max_records or emitted < max_records:
        target = min(batch_size, max_records - emitted) if max_records else batch_size
        fresh_target = max(1, int(round(target * fresh_weight)))
        fresh_rows = []
        for _ in range(fresh_target):
            try:
                fresh_rows.append(next(fresh))
            except StopIteration:
                break
        if not fresh_rows:
            break
        rehearsal_target = int(round(len(fresh_rows) * (1.0 - fresh_weight) / fresh_weight))
        if max_records:
            rehearsal_target = min(rehearsal_target, max_records - emitted - len(fresh_rows))
        rehearsal_rows = []
        for _ in range(rehearsal_target):
            try:
                rehearsal_rows.append(next(rehearsal))
            except StopIteration:
                rehearsal_cycle += 1
                rehearsal = iter(buffered_shuffle(
                    rehearsal_factory(), random.Random(seed + 10_000 + rehearsal_cycle), shuffle_buffer
                ))
                try:
                    rehearsal_rows.append(next(rehearsal))
                except StopIteration as exc:
                    raise ValueError("the filtered rehearsal source is empty") from exc
        batch = fresh_rows + rehearsal_rows
        rng.shuffle(batch)
        emitted += len(batch)
        yield batch


def weighted_row_batches(
    factories: dict[str, Callable[[], Iterable[dict]]],
    weights: dict[str, float],
    batch_size: int,
    seed: int,
    total_records: int,
    shuffle_buffer: int = 20_000,
) -> Iterator[list[dict]]:
    """Cycle named sources into deterministic batches with fixed target proportions."""
    if set(factories) != set(weights) or not factories:
        raise ValueError("factories and weights must have the same non-empty source names")
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("source weights must sum to one")
    rng = random.Random(seed)
    cycles = {name: 0 for name in factories}
    streams = {
        name: iter(buffered_shuffle(factory(), random.Random(seed + index * 10_000), shuffle_buffer))
        for index, (name, factory) in enumerate(factories.items(), 1)
    }
    emitted = 0
    names = list(factories)
    while emitted < total_records:
        target = min(batch_size, total_records - emitted)
        quotas = {name: int(math.floor(target * weights[name])) for name in names}
        for name in sorted(names, key=lambda value: weights[value], reverse=True)[: target - sum(quotas.values())]:
            quotas[name] += 1
        rows = []
        for source_name in names:
            for _ in range(quotas[source_name]):
                try:
                    row = next(streams[source_name])
                except StopIteration:
                    cycles[source_name] += 1
                    streams[source_name] = iter(buffered_shuffle(
                        factories[source_name](),
                        random.Random(seed + names.index(source_name) * 10_000 + cycles[source_name]),
                        shuffle_buffer,
                    ))
                    try:
                        row = next(streams[source_name])
                    except StopIteration as exc:
                        raise ValueError(f"filtered source is empty: {source_name}") from exc
                row["sample_source"] = source_name
                rows.append(row)
        rng.shuffle(rows)
        emitted += len(rows)
        yield rows


def iter_hard_rows(path: str | Path) -> Iterator[dict]:
    seen = set()
    for row in _jsonl_rows(path):
        key = row_key(row)
        if key in seen:
            continue
        seen.add(key)
        row["sample_source"] = "hard"
        yield row


def masked_count_distribution(logits: torch.Tensor, batch: dict) -> torch.Tensor:
    last_class = logits.shape[1] - 1
    minimum = torch.round(batch["global"][:, 28] * MAX_SELECT_COUNT).long().clamp(0, last_class)
    maximum = torch.round(batch["global"][:, 29] * MAX_SELECT_COUNT).long().clamp(0, last_class)
    maximum = torch.maximum(maximum, minimum)
    classes = torch.arange(logits.shape[1], device=logits.device).unsqueeze(0)
    valid = (classes >= minimum.unsqueeze(1)) & (classes <= maximum.unsqueeze(1))
    valid.scatter_(1, batch["counts"].unsqueeze(1), True)
    return logits.masked_fill(~valid, -torch.inf)


def policy_distillation_loss(
    student_logits: torch.Tensor,
    student_count: torch.Tensor,
    teacher_logits: torch.Tensor,
    teacher_count: torch.Tensor,
    batch: dict,
) -> tuple[torch.Tensor, torch.Tensor]:
    action_terms = []
    for record_index, (start, end) in enumerate(batch["record_options"]):
        available = torch.ones(end - start, dtype=torch.bool, device=student_logits.device)
        steps = max(1, len(batch["record_actions"][record_index]))
        local_terms = []
        for step in range(steps):
            # Slice legal entries instead of masking with -inf: KL's elementwise
            # 0 * -inf terms are NaN even though the mathematical limit is zero.
            step_available = available.clone()
            student = student_logits[start:end][step_available]
            teacher = teacher_logits[start:end][step_available]
            local_terms.append(F.kl_div(
                F.log_softmax(student, dim=0), F.softmax(teacher, dim=0), reduction="sum"
            ))
            actions = batch["record_actions"][record_index]
            if step < len(actions):
                available = step_available.clone()
                available[actions[step]] = False
                if not available.any():
                    break
        action_terms.append(torch.stack(local_terms).mean() * batch["weights"][record_index])
    action_kl = torch.stack(action_terms).sum() / batch["weights"].sum().clamp_min(1e-6)

    student_masked = masked_count_distribution(student_count, batch)
    teacher_masked = masked_count_distribution(teacher_count, batch)
    count_terms = []
    for index in range(student_masked.shape[0]):
        valid = torch.isfinite(student_masked[index]) & torch.isfinite(teacher_masked[index])
        count_terms.append(F.kl_div(
            F.log_softmax(student_masked[index, valid], dim=0),
            F.softmax(teacher_masked[index, valid], dim=0),
            reduction="sum",
        ))
    per_record = torch.stack(count_terms)
    count_kl = (per_record * batch["weights"]).sum() / batch["weights"].sum().clamp_min(1e-6)
    return action_kl, count_kl


def set_trainable_modules(model: PolicyNet, modules: Iterable[str]) -> tuple[str, ...]:
    requested = tuple(modules)
    known = {name for name, _ in model.named_children()}
    unknown = set(requested) - known
    if unknown:
        raise ValueError(f"unknown trainable modules: {sorted(unknown)}")
    for name, parameter in model.named_parameters():
        parameter.requires_grad = name.split(".", 1)[0] in requested
    return tuple(name for name, parameter in model.named_parameters() if parameter.requires_grad)


def _weighted_value_loss(values: torch.Tensor, batch: dict) -> torch.Tensor:
    losses = F.binary_cross_entropy_with_logits(values, batch["values"], reduction="none")
    return (losses * batch["weights"]).sum() / batch["weights"].sum().clamp_min(1e-6)


@torch.no_grad()
def validation_loss(
    model: PolicyNet,
    fresh_path: str | Path,
    manifest: dict,
    device: torch.device,
    batch_size: int,
    max_records: int = 0,
) -> dict:
    model.eval()
    totals = defaultdict(float)
    batch_rows = []

    def consume(rows: list[dict]):
        batch = move(collate(rows), device)
        logits, count_logits, values = model(batch)
        option, correct, single = policy_loss(logits, batch)
        count = masked_count_loss(count_logits, batch)
        value = _weighted_value_loss(values, batch)
        totals["loss"] += float((option + 0.25 * count + 0.10 * value).item()) * len(rows)
        totals["records"] += len(rows)
        totals["single_correct"] += correct
        totals["single"] += single

    for row in iter_split_rows(fresh_path, manifest, "internal_validation"):
        batch_rows.append(row)
        if len(batch_rows) == batch_size:
            consume(batch_rows)
            batch_rows = []
        if max_records and totals["records"] + len(batch_rows) >= max_records:
            break
    if batch_rows:
        consume(batch_rows)
    return {
        "records": int(totals["records"]),
        "loss": totals["loss"] / max(1, totals["records"]),
        "single_top1": totals["single_correct"] / max(1, totals["single"]),
    }


def train_candidate(
    *,
    control_model: str | Path,
    fresh_path: str | Path,
    rehearsal_path: str | Path,
    manifest: dict,
    output: str | Path,
    log_path: str | Path,
    learning_rate: float,
    seed: int,
    batch_size: int,
    epochs: int,
    patience: int,
    fresh_weight: float,
    distill_weight: float,
    trainable_modules: tuple[str, ...],
    team_weights: dict[str, float],
    device_name: str,
    max_train_records: int = 0,
    max_validation_records: int = 0,
    shuffle_buffer: int = 20_000,
    initial_model: str | Path | None = None,
    hard_path: str | Path | None = None,
    source_weights: dict[str, float] | None = None,
    epoch_records: int = 0,
    module_learning_rates: dict[str, float] | None = None,
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device = auto_device(device_name)
    teacher = PolicyNet(manifest["feature_version"])
    student = PolicyNet(manifest["feature_version"])
    load_npz_weights(teacher, control_model)
    load_npz_weights(student, initial_model or control_model)
    teacher.eval().to(device)
    for parameter in teacher.parameters():
        parameter.requires_grad = False
    trainable_parameters = set_trainable_modules(student, trainable_modules)
    frozen_before = {
        name: value.detach().cpu().clone()
        for name, value in student.state_dict().items()
        if name.split(".", 1)[0] not in trainable_modules
    }
    student.to(device)
    module_learning_rates = module_learning_rates or {}
    parameter_groups = []
    for module_name in trainable_modules:
        parameters = [parameter for name, parameter in student.named_parameters()
                      if name.split(".", 1)[0] == module_name and parameter.requires_grad]
        if parameters:
            parameter_groups.append({"params": parameters, "lr": module_learning_rates.get(module_name, learning_rate)})
    optimizer = torch.optim.AdamW(parameter_groups, lr=learning_rate, weight_decay=1e-5)
    output = Path(output)
    log_path = Path(log_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("")
    history = []
    best_state = None
    best_validation = float("inf")
    stale = 0
    started = time.time()
    for epoch in range(epochs):
        student.train()
        totals = defaultdict(float)

        fresh_factory = lambda: iter_split_rows(fresh_path, manifest, "train", "fresh", team_weights)
        rehearsal_factory = lambda: iter_split_rows(rehearsal_path, manifest, "train", "rehearsal", team_weights)
        if hard_path:
            selected_weights = source_weights or {"hard": 0.50, "fresh": 0.25, "rehearsal": 0.25}
            total = max_train_records or epoch_records
            if not total:
                raise ValueError("epoch_records is required for three-source targeted training")
            row_batches = weighted_row_batches(
                {
                    "hard": lambda: iter_hard_rows(hard_path),
                    "fresh": fresh_factory,
                    "rehearsal": rehearsal_factory,
                },
                selected_weights,
                batch_size,
                seed + epoch,
                total,
                shuffle_buffer,
            )
        else:
            row_batches = mixed_row_batches(
                fresh_factory,
                rehearsal_factory,
                batch_size,
                fresh_weight,
                seed + epoch,
                max_train_records,
                shuffle_buffer,
            )
        for rows in row_batches:
            batch = move(collate(rows), device)
            student_logits, student_count, student_values = student(batch)
            with torch.no_grad():
                teacher_logits, teacher_count, _ = teacher(batch)
            option, correct, single = policy_loss(student_logits, batch)
            count = masked_count_loss(student_count, batch)
            value = _weighted_value_loss(student_values, batch)
            action_kl, count_kl = policy_distillation_loss(
                student_logits, student_count, teacher_logits, teacher_count, batch
            )
            loss = option + 0.25 * count + 0.10 * value + distill_weight * (action_kl + 0.25 * count_kl)
            if not torch.isfinite(loss):
                diagnostics = {
                    "option": float(option.detach().cpu()),
                    "count": float(count.detach().cpu()),
                    "value": float(value.detach().cpu()),
                    "action_kl": float(action_kl.detach().cpu()),
                    "count_kl": float(count_kl.detach().cpu()),
                    "device": str(device),
                    "records": len(rows),
                }
                raise FloatingPointError(
                    f"non-finite candidate loss at epoch {epoch + 1}: {json.dumps(diagnostics, sort_keys=True)}"
                )
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                [parameter for parameter in student.parameters() if parameter.requires_grad], 1.0
            )
            optimizer.step()
            totals["loss"] += float(loss.item()) * len(rows)
            totals["option"] += float(option.item()) * len(rows)
            totals["count"] += float(count.item()) * len(rows)
            totals["value"] += float(value.item()) * len(rows)
            totals["action_kl"] += float(action_kl.item()) * len(rows)
            totals["count_kl"] += float(count_kl.item()) * len(rows)
            totals["records"] += len(rows)
            totals["fresh"] += sum(row["sample_source"] == "fresh" for row in rows)
            totals["rehearsal"] += sum(row["sample_source"] == "rehearsal" for row in rows)
            totals["hard"] += sum(row["sample_source"] == "hard" for row in rows)
            totals["single_correct"] += correct
            totals["single"] += single
        if not totals["records"]:
            raise RuntimeError("no training records matched the split and filters")
        validation = validation_loss(
            student, fresh_path, manifest, device, batch_size, max_validation_records
        )
        metrics = {
            "epoch": epoch + 1,
            "records": int(totals["records"]),
            "fresh_records": int(totals["fresh"]),
            "rehearsal_records": int(totals["rehearsal"]),
            "hard_records": int(totals["hard"]),
            "fresh_fraction": totals["fresh"] / totals["records"],
            "loss": totals["loss"] / totals["records"],
            "option_loss": totals["option"] / totals["records"],
            "count_loss": totals["count"] / totals["records"],
            "value_loss": totals["value"] / totals["records"],
            "action_kl": totals["action_kl"] / totals["records"],
            "count_kl": totals["count_kl"] / totals["records"],
            "single_top1": totals["single_correct"] / max(1, totals["single"]),
            "validation": validation,
            "device": str(device),
            "elapsed_seconds": time.time() - started,
        }
        history.append(metrics)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(metrics, sort_keys=True) + "\n")
        print(json.dumps({"candidate": output.stem, **metrics}, sort_keys=True), flush=True)
        if validation["loss"] < best_validation - 1e-6:
            best_validation = validation["loss"]
            best_state = {name: value.detach().cpu().clone() for name, value in student.state_dict().items()}
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                break
    if best_state is None:
        raise RuntimeError("candidate never produced a valid checkpoint")
    student.load_state_dict(best_state)
    for name, before in frozen_before.items():
        after = student.state_dict()[name].detach().cpu()
        if not torch.equal(before, after):
            raise AssertionError(f"frozen parameter changed: {name}")
    export_npz(student.cpu(), output)
    return {
        "output": str(output),
        "sha256": sha256_file(output),
        "learning_rate": learning_rate,
        "module_learning_rates": module_learning_rates,
        "initial_model": str(initial_model or control_model),
        "seed": seed,
        "best_validation_loss": best_validation,
        "epochs_completed": len(history),
        "trainable_parameters": list(trainable_parameters),
        "frozen_parameters_verified": True,
        "history": history,
    }


def _decision(logits: torch.Tensor, count_logits: torch.Tensor, batch: dict, record_index: int) -> list[int]:
    start, end = batch["record_options"][record_index]
    ranked = torch.argsort(logits[start:end], descending=True).cpu().tolist()
    last_class = count_logits.shape[1] - 1
    minimum = int(round(float(batch["global"][record_index, 28].cpu()) * MAX_SELECT_COUNT))
    maximum = int(round(float(batch["global"][record_index, 29].cpu()) * MAX_SELECT_COUNT))
    minimum = max(0, min(last_class, minimum))
    maximum = max(minimum, min(last_class, maximum, len(ranked)))
    if minimum == maximum:
        desired = maximum
    else:
        desired = minimum + int(torch.argmax(count_logits[record_index, minimum : maximum + 1]).cpu())
    return ranked[:desired]


def _empty_decision_metrics() -> dict:
    return {"records": 0, "exact": 0, "count_correct": 0, "single": 0, "top1": 0}


def _update_decision_metrics(bucket: dict, elite: list[int], predicted: list[int], ranked_first: int | None):
    bucket["records"] += 1
    bucket["exact"] += int(set(elite) == set(predicted))
    bucket["count_correct"] += int(len(elite) == len(predicted))
    if len(elite) == 1:
        bucket["single"] += 1
        bucket["top1"] += int(ranked_first == elite[0])


def _finalize_decision_metrics(bucket: dict) -> dict:
    return {
        **bucket,
        "exact_rate": bucket["exact"] / max(1, bucket["records"]),
        "count_accuracy": bucket["count_correct"] / max(1, bucket["records"]),
        "single_top1": bucket["top1"] / max(1, bucket["single"]),
    }


@torch.no_grad()
def evaluate_model_pair(
    baseline_path: str | Path,
    candidate_path: str | Path,
    fresh_path: str | Path,
    manifest: dict,
    split: str,
    batch_size: int,
    device_name: str,
    max_records: int = 0,
) -> dict:
    device = auto_device(device_name)
    models = {}
    for name, path in (("baseline", baseline_path), ("candidate", candidate_path)):
        model = PolicyNet(manifest["feature_version"])
        load_npz_weights(model, path)
        models[name] = model.eval().to(device)
    metrics = {name: _empty_decision_metrics() for name in models}
    contexts = {name: defaultdict(_empty_decision_metrics) for name in models}
    seats = {name: defaultdict(_empty_decision_metrics) for name in models}
    first_orders = {name: defaultdict(_empty_decision_metrics) for name in models}
    errors = {name: 0 for name in models}
    rows = []
    consumed = 0

    def consume(batch_rows: list[dict]):
        batch = move(collate(batch_rows), device)
        for name, model in models.items():
            try:
                logits, count_logits, _ = model(batch)
                for index, row in enumerate(batch_rows):
                    predicted = _decision(logits, count_logits, batch, index)
                    start, end = batch["record_options"][index]
                    first = int(torch.argmax(logits[start:end]).cpu()) if end > start else None
                    context = str(row["features"]["options"][0]["context"] if row["features"]["options"] else -1)
                    seat = str(int(row.get("seat", round(row["features"]["global"][2]))))
                    first_order = "first" if row["features"]["global"][3] >= 0.5 else "second"
                    _update_decision_metrics(metrics[name], row["action"], predicted, first)
                    _update_decision_metrics(contexts[name][context], row["action"], predicted, first)
                    _update_decision_metrics(seats[name][seat], row["action"], predicted, first)
                    _update_decision_metrics(first_orders[name][first_order], row["action"], predicted, first)
            except Exception:
                errors[name] += len(batch_rows)

    for row in iter_split_rows(fresh_path, manifest, split):
        rows.append(row)
        consumed += 1
        if len(rows) == batch_size:
            consume(rows)
            rows = []
        if max_records and consumed >= max_records:
            break
    if rows:
        consume(rows)
    report = {
        "split": split,
        "baseline": _finalize_decision_metrics(metrics["baseline"]),
        "candidate": _finalize_decision_metrics(metrics["candidate"]),
        "by_context": {
            name: {key: _finalize_decision_metrics(value) for key, value in sorted(buckets.items())}
            for name, buckets in contexts.items()
        },
        "by_seat": {
            name: {key: _finalize_decision_metrics(value) for key, value in sorted(buckets.items())}
            for name, buckets in seats.items()
        },
        "by_first_order": {
            name: {key: _finalize_decision_metrics(value) for key, value in sorted(buckets.items())}
            for name, buckets in first_orders.items()
        },
        "policy_errors": errors,
    }
    report["delta"] = {
        key: report["candidate"][key] - report["baseline"][key]
        for key in ("exact_rate", "count_accuracy", "single_top1")
    }
    return report


def heldout_gate(reports: dict[str, dict], overall_tolerance: float = 0.0025, context_tolerance: float = 0.02) -> dict:
    reasons = []
    for split in ("team_holdout", "temporal"):
        report = reports[split]
        if any(report["policy_errors"].values()):
            reasons.append(f"{split}: policy errors")
        for metric in ("exact_rate", "count_accuracy"):
            if report["delta"][metric] < -overall_tolerance:
                reasons.append(f"{split}: {metric} delta {report['delta'][metric]:.6f}")
        baseline_contexts = report["by_context"]["baseline"]
        candidate_contexts = report["by_context"]["candidate"]
        for context, baseline in baseline_contexts.items():
            if baseline["records"] < 500:
                continue
            delta = candidate_contexts[context]["exact_rate"] - baseline["exact_rate"]
            if delta < -context_tolerance:
                reasons.append(f"{split}: context {context} exact delta {delta:.6f}")
        for grouping in ("by_seat", "by_first_order"):
            for key, baseline in report[grouping]["baseline"].items():
                candidate = report[grouping]["candidate"][key]
                delta = candidate["exact_rate"] - baseline["exact_rate"]
                if delta < -overall_tolerance:
                    reasons.append(f"{split}: {grouping} {key} exact delta {delta:.6f}")
    return {"passed": not reasons, "reasons": reasons}


def run_match(
    *,
    deck_a: str | Path,
    model_a: str | Path,
    deck_b: str | Path,
    model_b: str | Path = "",
    games: int,
    workers: int,
    output: str | Path,
    seed: int,
    submission_b: str | Path = "",
) -> dict:
    command = [
        sys.executable,
        str(ROOT / "training" / "evaluate.py"),
        "--deck-a", str(deck_a), "--model-a", str(model_a),
        "--deck-b", str(deck_b), "--games", str(games),
        "--workers", str(workers), "--output", str(output), "--seed", str(seed),
    ]
    if model_b:
        command.extend(["--model-b", str(model_b)])
    if submission_b:
        command.extend(["--submission-b", str(submission_b)])
    subprocess.run(command, cwd=ROOT, check=True)
    return json.loads(Path(output).read_text())


def _candidate_name(learning_rate: float, seed: int) -> str:
    return f"lr{learning_rate:.0e}_seed{seed}".replace("+", "")


def _write_json(path: str | Path, value: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def _verify_control(archive: Path, control: Path, deck: Path) -> dict:
    hashes = {
        "archive": sha256_file(archive),
        "control_model": sha256_file(control),
        "archive_model": sha256_archive_member(archive, "policy_weights.npz"),
        "deck": sha256_file(deck),
        "archive_deck": sha256_archive_member(archive, "deck.csv"),
    }
    expected = {
        "archive": EXPECTED_ARCHIVE_SHA256,
        "control_model": EXPECTED_CONTROL_SHA256,
        "archive_model": EXPECTED_CONTROL_SHA256,
        "deck": EXPECTED_DECK_SHA256,
        "archive_deck": EXPECTED_DECK_SHA256,
    }
    mismatches = {name: [hashes[name], value] for name, value in expected.items() if hashes[name] != value}
    if mismatches:
        raise ValueError(f"live control verification failed: {mismatches}")
    return hashes


def run_experiment(args: argparse.Namespace) -> dict:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    control = Path(args.control_model).resolve()
    fresh = Path(args.fresh).resolve()
    rehearsal = Path(args.rehearsal).resolve()
    deck = Path(args.deck).resolve()
    archive = Path(args.control_archive).resolve()
    control_hashes = _verify_control(archive, control, deck)
    if not math.isclose(args.fresh_weight + args.rehearsal_weight, 1.0, abs_tol=1e-9):
        raise ValueError("fresh and rehearsal weights must sum to one")
    manifest = (
        json.loads(Path(args.split_manifest).read_text())
        if args.split_manifest
        else build_split_manifest(
            fresh, rehearsal, args.temporal_replays, args.require_card, args.feature_version
        )
    )
    _write_json(output_dir / "split_manifest.json", manifest)
    team_weights, team_rank_snapshot = load_team_weights(args.team_ranks)
    learning_rates = [float(value) for value in args.learning_rates.split(",") if value]
    seeds = [int(value) for value in args.seeds.split(",") if value]
    matrix = [(lr, seed) for lr in learning_rates for seed in seeds]
    if args.candidate_limit:
        matrix = matrix[: args.candidate_limit]
    trainable_modules = tuple(value.strip() for value in args.trainable_modules.split(",") if value.strip())
    experiment = {
        "version": 1,
        "experiment_only": True,
        "submitted": False,
        "package_created": False,
        "created_unix": time.time(),
        "inputs": {
            "control_archive": str(archive),
            "control_model": str(control),
            "deck": str(deck),
            "fresh": str(fresh),
            "rehearsal": str(rehearsal),
            "temporal_replays": str(Path(args.temporal_replays).resolve()),
            "split_manifest_input": str(Path(args.split_manifest).resolve()) if args.split_manifest else None,
            "hashes": {
                **control_hashes,
                "fresh": sha256_file(fresh),
                "rehearsal": sha256_file(rehearsal),
                "team_ranks": sha256_file(args.team_ranks) if args.team_ranks else None,
            },
        },
        "configuration": {
            "source_weights": {"fresh": args.fresh_weight, "rehearsal": args.rehearsal_weight},
            "distill_weight": args.distill_weight,
            "trainable_modules": list(trainable_modules),
            "learning_rates": learning_rates,
            "seeds": seeds,
            "batch_size": args.batch_size,
            "epochs": args.epochs,
            "patience": args.patience,
            "device_requested": args.device,
            "device_resolved": str(auto_device(args.device)),
            "team_rank_snapshot": team_rank_snapshot,
            "max_train_records": args.max_train_records,
            "max_evaluation_records": args.max_evaluation_records,
            "matches_skipped": args.skip_matches,
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "torch": torch.__version__,
            "numpy": np.__version__,
            "cpu_count": os.cpu_count(),
        },
        "split_manifest": "split_manifest.json",
    }
    _write_json(output_dir / "experiment.json", experiment)

    candidates = []
    for learning_rate, seed in matrix:
        name = _candidate_name(learning_rate, seed)
        candidate_dir = output_dir / "candidates" / name
        decision_path = candidate_dir / "decision_evaluation.json"
        training_path = candidate_dir / "training_result.json"
        if args.resume and decision_path.exists():
            candidate = json.loads(decision_path.read_text())
            if sha256_file(candidate["training"]["output"]) != candidate["training"]["sha256"]:
                raise ValueError(f"resume checkpoint hash mismatch for {name}")
            candidates.append(candidate)
            print(json.dumps({"candidate": name, "resume": "decision_evaluation"}), flush=True)
            continue
        if args.resume and training_path.exists():
            result = json.loads(training_path.read_text())
            if sha256_file(result["output"]) != result["sha256"]:
                raise ValueError(f"resume checkpoint hash mismatch for {name}")
            print(json.dumps({"candidate": name, "resume": "training"}), flush=True)
        else:
            result = train_candidate(
                control_model=control,
                fresh_path=fresh,
                rehearsal_path=rehearsal,
                manifest=manifest,
                output=candidate_dir / "policy_weights.npz",
                log_path=candidate_dir / "training.jsonl",
                learning_rate=learning_rate,
                seed=seed,
                batch_size=args.batch_size,
                epochs=args.epochs,
                patience=args.patience,
                fresh_weight=args.fresh_weight,
                distill_weight=args.distill_weight,
                trainable_modules=trainable_modules,
                team_weights=team_weights,
                device_name=args.device,
                max_train_records=args.max_train_records,
                max_validation_records=args.max_evaluation_records,
                shuffle_buffer=args.shuffle_buffer,
            )
            _write_json(training_path, result)
        reports = {}
        for split in ("internal_validation", "team_holdout", "temporal"):
            reports[split] = evaluate_model_pair(
                control,
                result["output"],
                fresh,
                manifest,
                split,
                args.batch_size,
                args.device,
                args.max_evaluation_records,
            )
        gate = heldout_gate(reports)
        candidate = {"name": name, "training": result, "decision_reports": reports, "heldout_gate": gate}
        _write_json(decision_path, candidate)
        candidates.append(candidate)

    if args.skip_matches:
        report = {
            "experiment_only": True,
            "submitted": False,
            "package_created": False,
            "status": "decision_evaluation_complete_matches_skipped",
            "candidates": candidates,
        }
        _write_json(output_dir / "final_report.json", report)
        return report

    eligible = [candidate for candidate in candidates if candidate["heldout_gate"]["passed"]]
    screen_results = []
    for index, candidate in enumerate(eligible):
        output = output_dir / "matches" / "screen" / f"{candidate['name']}.json"
        match = run_match(
            deck_a=deck,
            model_a=candidate["training"]["output"],
            deck_b=deck,
            model_b=control,
            games=args.screen_games,
            workers=args.workers,
            output=output,
            seed=args.match_seed + index * 100_000,
        )
        screen_results.append({"candidate": candidate, "match": match})
    screen_results.sort(key=lambda item: (
        item["match"]["win_rate_a"],
        item["match"]["wilson_95"][0],
        item["candidate"]["decision_reports"]["temporal"]["candidate"]["exact_rate"],
    ), reverse=True)
    top_three = screen_results[:3]

    semifinal_results = []
    for index, item in enumerate(top_three):
        candidate = item["candidate"]
        output = output_dir / "matches" / "semifinal" / f"{candidate['name']}.json"
        match = run_match(
            deck_a=deck,
            model_a=candidate["training"]["output"],
            deck_b=deck,
            model_b=control,
            games=args.semifinal_games,
            workers=args.workers,
            output=output,
            seed=args.match_seed + 1_000_000 + index * 100_000,
        )
        seats = match["seat_results_a"]
        advanced = (
            match["win_rate_a"] >= 0.51
            and min(value["win_rate"] for value in seats.values()) >= 0.48
            and match["hero_policy_errors"] == 0
            and candidate["heldout_gate"]["passed"]
        )
        semifinal_results.append({"candidate": candidate, "match": match, "advanced": advanced})
    semifinal_results.sort(key=lambda item: (item["advanced"], item["match"]["win_rate_a"]), reverse=True)
    finalist = semifinal_results[0] if semifinal_results and semifinal_results[0]["advanced"] else None

    final_match = None
    authentic = {}
    success = False
    if finalist:
        candidate = finalist["candidate"]
        final_match = run_match(
            deck_a=deck,
            model_a=candidate["training"]["output"],
            deck_b=deck,
            model_b=control,
            games=args.final_games,
            workers=args.workers,
            output=output_dir / "matches" / "final.json",
            seed=args.match_seed + 2_000_000,
        )
        external_entries = json.loads(Path(args.authentic_league).read_text())["opponents"]
        authentic_pass = True
        for index, entry in enumerate(external_entries):
            if not entry.get("evaluate"):
                continue
            opponent_deck = ROOT / entry["deck"]
            submission = ROOT / entry["submission"]
            paired_seed = args.match_seed + 3_000_000 + index * 100_000
            baseline = run_match(
                deck_a=deck, model_a=control, deck_b=opponent_deck,
                games=args.authentic_games, workers=args.workers,
                output=output_dir / "matches" / "authentic" / f"{entry['name']}_baseline.json",
                seed=paired_seed, submission_b=submission,
            )
            challenger = run_match(
                deck_a=deck, model_a=candidate["training"]["output"], deck_b=opponent_deck,
                games=args.authentic_games, workers=args.workers,
                output=output_dir / "matches" / "authentic" / f"{entry['name']}_candidate.json",
                seed=paired_seed, submission_b=submission,
            )
            passed = challenger["win_rate_a"] >= baseline["win_rate_a"] - 0.03 and challenger["hero_policy_errors"] == 0
            authentic_pass &= passed
            authentic[entry["name"]] = {"baseline": baseline, "candidate": challenger, "passed": passed}
        seats = final_match["seat_results_a"]
        success = (
            final_match["wilson_95"][0] > 0.50
            and min(value["win_rate"] for value in seats.values()) >= 0.50
            and final_match["hero_policy_errors"] == 0
            and candidate["heldout_gate"]["passed"]
            and authentic_pass
        )

    report = {
        "experiment_only": True,
        "submitted": False,
        "package_created": False,
        "status": "success" if success else "no_candidate_passed_strict_gate",
        "success": success,
        "screen": [{"name": item["candidate"]["name"], "match": item["match"]} for item in screen_results],
        "semifinal": [
            {"name": item["candidate"]["name"], "match": item["match"], "advanced": item["advanced"]}
            for item in semifinal_results
        ],
        "finalist": finalist["candidate"]["name"] if finalist else None,
        "final": final_match,
        "authentic": authentic,
    }
    _write_json(output_dir / "final_report.json", report)
    return report


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--control-archive", default="grimmsnarl_5k_reference.tar.gz")
    result.add_argument("--control-model", default="artifacts/grimmsnarl_5k_reference.npz")
    result.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    result.add_argument("--fresh", default="data/processed/elite-2026-07-30-31-v2ctl.jsonl.gz")
    result.add_argument("--rehearsal", default="data/processed/elite-2026-07-28-v2ctl.jsonl.gz")
    result.add_argument("--temporal-replays", default="data/replays/2026-07-31")
    result.add_argument("--split-manifest", help="reuse an explicit previously generated split manifest")
    result.add_argument("--team-ranks", default="data/top_teams.txt")
    result.add_argument("--output-dir", default="artifacts/5k_replay_refresh_20260802")
    result.add_argument("--require-card", type=int, default=648)
    result.add_argument("--feature-version", type=int, default=2)
    result.add_argument("--fresh-weight", type=float, default=0.75)
    result.add_argument("--rehearsal-weight", type=float, default=0.25)
    result.add_argument("--distill-weight", type=float, default=0.50)
    result.add_argument("--trainable-modules", default=",".join(DEFAULT_TRAINABLE_MODULES))
    result.add_argument("--learning-rates", default="1e-5,3e-5,1e-4")
    result.add_argument("--seeds", default="20260802,20260803,20260804")
    result.add_argument("--batch-size", type=int, default=256)
    result.add_argument("--epochs", type=int, default=3)
    result.add_argument("--patience", type=int, default=1)
    result.add_argument("--device", choices=("auto", "cpu", "cuda", "mps"), default="auto")
    result.add_argument("--shuffle-buffer", type=int, default=20_000)
    result.add_argument("--max-train-records", type=int, default=0)
    result.add_argument("--max-evaluation-records", type=int, default=0)
    result.add_argument("--candidate-limit", type=int, default=0)
    result.add_argument("--resume", action="store_true", help="reuse hash-verified candidate checkpoints and reports")
    result.add_argument("--skip-matches", action="store_true")
    result.add_argument("--screen-games", type=int, default=500)
    result.add_argument("--semifinal-games", type=int, default=2_000)
    result.add_argument("--final-games", type=int, default=10_000)
    result.add_argument("--authentic-games", type=int, default=200)
    result.add_argument("--authentic-league", default="training/external_alakazam_benchmark.json")
    result.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    result.add_argument("--match-seed", type=int, default=20260802)
    return result


def main() -> int:
    args = parser().parse_args()
    report = run_experiment(args)
    print(json.dumps({
        "output_dir": str(Path(args.output_dir).resolve()),
        "status": report["status"],
        "experiment_only": True,
        "submitted": False,
        "package_created": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
