#!/usr/bin/env python3
"""Label on-policy schema-5 states only when three of four clones agree."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

import torch
import numpy as np

from training.lucario_data import deterministic_gzip_text, sha256_file
from training.schema5 import DirectPolicyNet, greedy_complete_actions, load_direct
from training.schema5_relational import RelationalDirectPolicyNet, load_relational
from training.train_bc import collate


def input_rows(paths):
    seen = set()
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if int(row.get("features", {}).get("feature_version", -1)) != 5:
                    raise ValueError(f"non-schema-5 on-policy row: {path}")
                key = (str(row["episode_id"]), int(row["seat"]), int(row["step"]))
                if key in seen:
                    raise RuntimeError(f"duplicate on-policy decision: {key}")
                seen.add(key)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--clones", nargs=4, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    clone_paths = [ROOT / path for path in args.clones]
    if len({hashlib.sha256(path.read_bytes()).hexdigest() for path in clone_paths}) != 4:
        raise RuntimeError("consensus requires four independent clone artifacts")
    models = []
    for path in clone_paths:
        with np.load(path, allow_pickle=False) as artifact:
            version = int(np.asarray(artifact["direct_model_version"]).item())
        if version == 1:
            model = DirectPolicyNet().eval()
            load_direct(model, path)
        elif version == 2:
            model = RelationalDirectPolicyNet().eval()
            load_relational(model, path)
        else:
            raise RuntimeError(f"unsupported clone model version {version}: {path}")
        models.append(model)

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    total = retained = disagreements = 0
    by_order = Counter()
    with deterministic_gzip_text(output) as handle, torch.no_grad():
        for source_rows in chunks(input_rows([ROOT / path for path in args.inputs]), args.batch_size):
            batch = collate(source_rows)
            votes = []
            for model in models:
                logits, counts = model(batch)
                votes.append([tuple(action) for action in greedy_complete_actions(logits, counts, batch)])
            for index, row in enumerate(source_rows):
                total += 1
                action, support = Counter(vote[index] for vote in votes).most_common(1)[0]
                if support < 3:
                    continue
                retained += 1
                old_action = [int(value) for value in row["action"]]
                disagreements += list(action) != old_action
                labeled = dict(row)
                labeled["action"] = list(action)
                labeled["rejected_action"] = old_action if list(action) != old_action else None
                labeled["objective_source"] = "on_policy_four_clone_consensus"
                labeled["consensus_support"] = support
                labeled["split"] = "train"
                by_order[str(row.get("hero_order") or "unknown")] += 1
                handle.write(json.dumps(labeled, separators=(",", ":")) + "\n")
    manifest = {
        "status": "complete",
        "feature_version": 5,
        "input_rows": total,
        "retained_rows": retained,
        "retention_rate": retained / max(1, total),
        "candidate_disagreements": disagreements,
        "by_actual_order": dict(by_order),
        "clone_models": [
            {"path": str(path.resolve()), "sha256": sha256_file(path)} for path in clone_paths
        ],
        "output": str(output.resolve()),
        "output_sha256": sha256_file(output),
    }
    manifest_path = ROOT / args.manifest if args.manifest else output.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
