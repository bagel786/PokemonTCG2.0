#!/usr/bin/env python3
"""Evaluate a direct schema-5 policy against held-out actions and packaged R0."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np
import torch

from ptcg_ai.relational import _complete_score
from training.schema4 import RelationalResidualNet, legacy_a2_batch, load_residual
from training.schema5 import DirectPolicyNet, greedy_complete_actions, load_direct
from training.schema5_relational import RelationalDirectPolicyNet, load_relational
from training.train_bc import PolicyNet, collate, load_npz_weights, move

R0_ARCHIVE_SHA256 = "AC0E9B174AE99911AD9E04F82E912E43AB7E9FFA130D297C04FEDCF34247058B"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def rows(path: Path, split: str):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if int(row.get("features", {}).get("feature_version", -1)) != 5:
                raise ValueError("schema-4 data cannot enter a schema-5 evaluation")
            if split == "all" or row.get("split") == split:
                yield row


def chunks(values, size):
    current = []
    for value in values:
        current.append(value)
        if len(current) == size:
            yield current
            current = []
    if current:
        yield current


def complete_action(logits, counts, minimum, maximum):
    maximum = min(maximum, len(counts) - 1, len(logits))
    minimum = min(minimum, maximum)
    desired = minimum if minimum == maximum else minimum + int(np.argmax(counts[minimum:maximum + 1]))
    return tuple(np.argsort(-np.asarray(logits), kind="stable")[:desired].astype(int).tolist())


def bounds(batch, record_index):
    minimum = int(round(float(batch["global"][record_index, 28]) * 9))
    maximum = int(round(float(batch["global"][record_index, 29]) * 9))
    return minimum, maximum


def r0_actions(batch, base, heads, support_margin):
    relational = dict(batch)
    relational["source"] = torch.where(batch["type"] == 3, batch["target"], batch["source"])
    relational["source_entity"] = torch.where(
        batch["type"] == 3, batch["target_entity"], batch["source_entity"]
    )
    base_logits, base_counts, _ = base(legacy_a2_batch(relational))
    predictions = [head(relational) for head in heads]
    base_logits = base_logits.cpu().numpy()
    base_counts = base_counts.cpu().numpy()
    residual_logits = [prediction[0].cpu().numpy() for prediction in predictions]
    residual_counts = [prediction[1].cpu().numpy() for prediction in predictions]
    result = []
    for record_index, (start, end) in enumerate(batch["record_options"]):
        minimum, maximum = bounds(batch, record_index)
        base_action = complete_action(base_logits[start:end], base_counts[record_index], minimum, maximum)
        types = batch["type"][start:end].cpu().numpy()
        context = int(batch["context"][start])
        eligible = context == 0 and int(np.sum(types == 7)) >= 2
        if not eligible:
            result.append(base_action)
            continue
        head_actions, logits_by_head, counts_by_head = [], [], []
        for head_index in range(3):
            logits = base_logits[start:end] + residual_logits[head_index][start:end]
            counts = base_counts[record_index] + residual_counts[head_index][record_index]
            logits_by_head.append(logits)
            counts_by_head.append(counts)
            head_actions.append(complete_action(logits, counts, minimum, maximum))
        candidate, support = Counter(head_actions).most_common(1)[0]
        mean_logits = np.mean(logits_by_head, axis=0)
        mean_counts = np.mean(counts_by_head, axis=0)
        select = SimpleNamespace(minCount=minimum, maxCount=maximum)
        margin = _complete_score(mean_logits, mean_counts, candidate, select)
        margin -= _complete_score(mean_logits, mean_counts, base_action, select)
        result.append(candidate if support >= 2 and (candidate == base_action or margin >= support_margin) else base_action)
    return result


def categories(row: dict) -> set[str]:
    options = row["features"]["options"]
    contexts = {int(option["context"]) for option in options}
    types = {int(option["option_type"]) for option in options}
    result = {"overall"}
    if len(options) > 1 or int(row["features"]["global"][28] * 9) != int(row["features"]["global"][29] * 9):
        result.add("branching")
    if 0 in contexts:
        result.add("MAIN")
    if 8 in types:
        result.add("attachment")
    if 9 in types:
        result.add("evolution")
    if contexts & {3, 4, 5, 6, 25, 35, 36}:
        result.add("attack_target")
    if contexts & {7, 8, 9, 10, 11, 12, 24, 34, 38}:
        result.add("search_target")
    if contexts & {39, 40}:
        result.add("damage_removal")
    if (
        int(row.get("own_turn_ordinal") or 0) == 2
        and any(int(option["option_type"]) == 8 and int(option["target_card"]) == 112 for option in options)
    ):
        result.add("turn_two_munkidori_attachment")
    return result


def update_metric(metric: Counter, truth, r0, direct):
    metric["records"] += 1
    metric["r0_exact"] += truth == r0
    metric["direct_exact"] += truth == direct


def normalize(metric: Counter) -> dict:
    records = int(metric["records"])
    if records <= 0:
        return {"records": 0, "r0_complete_agreement": None, "direct_complete_agreement": None, "uplift_points": None}
    r0 = metric["r0_exact"] / records
    direct = metric["direct_exact"] / records
    return {
        "records": records,
        "r0_complete_agreement": r0,
        "direct_complete_agreement": direct,
        "uplift_points": 100 * (direct - r0),
    }


def selected_distribution(source_rows, actions, key):
    counts = Counter()
    for row, action in zip(source_rows, actions):
        for index in action:
            option = row["features"]["options"][index]
            value = int(option.get(key, 0) or 0)
            if value:
                counts[str(value)] += 1
    total = sum(counts.values())
    return {name: count / max(1, total) for name, count in sorted(counts.items())}


def sequence_statistics(source_rows, actions):
    attack_turns = Counter()
    attacks = munkidori_attachments = target_choices = 0
    for row, action in zip(source_rows, actions):
        for index in action:
            option = row["features"]["options"][index]
            option_type = int(option.get("option_type", 0) or 0)
            if option_type == 13:
                attacks += 1
                attack_turns[str(int(row.get("own_turn_ordinal") or 0))] += 1
            if option_type == 8 and int(option.get("target_card", 0) or 0) == 112:
                munkidori_attachments += 1
            if int(option.get("target_card", 0) or 0):
                target_choices += 1
    records = max(1, len(source_rows))
    return {
        "attack_action_rate": attacks / records,
        "munkidori_attachment_rate": munkidori_attachments / records,
        "target_choice_rate": target_choices / records,
        "attack_turn_distribution": {
            turn: count / max(1, attacks) for turn, count in sorted(attack_turns.items(), key=lambda item: int(item[0]))
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stream")
    parser.add_argument("--direct", required=True)
    parser.add_argument("--r0-root", default="artifacts/recovery_r0_package/extracted/r0_play_binding")
    parser.add_argument("--r0-archive", default="artifacts/recovery_r0_package/r0_play_binding.tar.gz")
    parser.add_argument("--output", required=True)
    parser.add_argument("--split", default="all")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()

    archive = ROOT / args.r0_archive
    actual_r0_hash = sha256_file(archive)
    if actual_r0_hash != R0_ARCHIVE_SHA256:
        raise RuntimeError(f"R0 label/hash mismatch: {actual_r0_hash}")
    root = ROOT / args.r0_root
    base = PolicyNet(2).eval()
    load_npz_weights(base, root / "a2_base.npz")
    heads = []
    for index in range(3):
        head = RelationalResidualNet("r0").eval()
        load_residual(head, root / f"residual_head_{index}.npz")
        heads.append(head)
    support_margin = max(float(np.load(root / f"residual_head_{index}.npz")["support_margin"]) for index in range(3))
    direct_path = ROOT / args.direct
    with np.load(direct_path, allow_pickle=False) as artifact:
        direct_version = int(np.asarray(artifact["direct_model_version"]).item())
    if direct_version == 1:
        direct = DirectPolicyNet().eval()
        load_direct(direct, direct_path)
    elif direct_version == 2:
        direct = RelationalDirectPolicyNet().eval()
        load_relational(direct, direct_path)
    else:
        raise RuntimeError(f"unsupported direct model version {direct_version}")

    overall = Counter()
    strata = defaultdict(Counter)
    episodes = defaultdict(lambda: [0, 0, 0])
    truth_selected, r0_selected, direct_selected = [], [], []
    all_rows = []
    with torch.no_grad():
        for source_rows in chunks(rows(ROOT / args.stream, args.split), args.batch_size):
            batch = move(collate(source_rows), torch.device("cpu"))
            logits, counts = direct(batch)
            direct_batch = [tuple(action) for action in greedy_complete_actions(logits, counts, batch)]
            r0_batch = r0_actions(batch, base, heads, support_margin)
            for row, truth_list, r0, candidate in zip(source_rows, batch["record_actions"], r0_batch, direct_batch):
                truth = tuple(truth_list)
                update_metric(overall, truth, r0, candidate)
                order = str(row.get("hero_order") or "unknown")
                for category in categories(row):
                    update_metric(strata[f"category:{category}"], truth, r0, candidate)
                    update_metric(strata[f"order:{order}|category:{category}"], truth, r0, candidate)
                episode = episodes[str(row["episode_id"])]
                episode[0] += int(candidate == truth) - int(r0 == truth)
                episode[1] += 1
                episode[2] += int(candidate != r0)
                all_rows.append(row)
                truth_selected.append(truth)
                r0_selected.append(r0)
                direct_selected.append(candidate)
    if not overall["records"]:
        raise RuntimeError("evaluation stream produced zero rows")

    clusters = np.asarray([[value[0], value[1]] for value in episodes.values()], dtype=np.float64)
    rng = np.random.default_rng(20260808)
    bootstrap = np.empty(10_000)
    for index in range(len(bootstrap)):
        sample = clusters[rng.integers(0, len(clusters), len(clusters))]
        bootstrap[index] = sample[:, 0].sum() / max(1, sample[:, 1].sum())
    report = {
        "status": "complete",
        "feature_version": 5,
        "direct_model_version": direct_version,
        "stream": str((ROOT / args.stream).resolve()),
        "stream_sha256": sha256_file(ROOT / args.stream),
        "direct_model": str((ROOT / args.direct).resolve()),
        "direct_model_sha256": sha256_file(ROOT / args.direct),
        "r0_archive_sha256": actual_r0_hash,
        "overall": normalize(overall),
        "episode_clusters": len(episodes),
        "episode_bootstrap_uplift_95_points": [
            100 * float(np.quantile(bootstrap, .025)), 100 * float(np.quantile(bootstrap, .975))
        ],
        "strata": {name: normalize(metric) for name, metric in sorted(strata.items())},
        "override_rate": sum(value[2] for value in episodes.values()) / overall["records"],
        "selected_source_card_distribution": {
            "teacher": selected_distribution(all_rows, truth_selected, "source_card"),
            "r0": selected_distribution(all_rows, r0_selected, "source_card"),
            "direct": selected_distribution(all_rows, direct_selected, "source_card"),
        },
        "selected_target_card_distribution": {
            "teacher": selected_distribution(all_rows, truth_selected, "target_card"),
            "r0": selected_distribution(all_rows, r0_selected, "target_card"),
            "direct": selected_distribution(all_rows, direct_selected, "target_card"),
        },
        "sequence_statistics": {
            "teacher": sequence_statistics(all_rows, truth_selected),
            "r0": sequence_statistics(all_rows, r0_selected),
            "direct": sequence_statistics(all_rows, direct_selected),
        },
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "overall": report["overall"],
        "bootstrap": report["episode_bootstrap_uplift_95_points"],
        "branching": report["strata"].get("category:branching"),
        "MAIN": report["strata"].get("category:MAIN"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
