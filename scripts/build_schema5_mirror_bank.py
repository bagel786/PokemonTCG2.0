#!/usr/bin/env python3
"""Build untouched high-leverage mirror evaluation slices from schema-5 rows."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

from training.lucario_data import deterministic_gzip_text, sha256_file

MUNKIDORI = 112
GRIMMSNARL = 648
POKE_PAD = 1152
SHADOW_BULLET = 937
SEQUENCING_CARDS = {1079, 1086, 1097, 1122, 1152, 1219, 1227, 1231, 1259}


def rows(paths):
    seen = set()
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if int(row.get("features", {}).get("feature_version", -1)) != 5:
                    raise ValueError(f"mirror bank refuses non-schema-5 data: {path}")
                key = str(row["episode_id"]), int(row["seat"]), int(row["step"])
                if key in seen:
                    continue
                seen.add(key)
                yield row


def selected_options(row):
    options = row["features"]["options"]
    return [options[index] for index in row["action"] if 0 <= index < len(options)]


def categories(row):
    options = row["features"]["options"]
    contexts = {int(option["context"]) for option in options}
    result = []
    if int(row.get("own_turn_ordinal") or 0) == 2 and any(
        int(option["option_type"]) == 8 and int(option["target_card"]) == MUNKIDORI
        for option in options
    ):
        result.append("turn_two_munkidori_attachment")
    if 16 in contexts:
        targets = {int(option["target_card"]) for option in options if int(option["source_card"]) == MUNKIDORI}
        if {MUNKIDORI, GRIMMSNARL} <= targets:
            result.append("adrena_brain_own_damage_source")
    if any(int(option["attack_id"]) == SHADOW_BULLET for option in options):
        result.append("shadow_bullet_ready")
        if any(int(option["attack_id"]) == SHADOW_BULLET for option in selected_options(row)):
            result.append("shadow_bullet_conversion")
    if any(int(option["source_card"]) == POKE_PAD for option in options):
        result.append("poke_pad_and_search_composition")
    if 0 in contexts and any(int(option["source_card"]) in SEQUENCING_CARDS for option in options):
        result.append("evolution_recovery_draw_sequencing")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+")
    parser.add_argument("--output-root", default="data/grim_breakthrough_v5/mirror_bank")
    args = parser.parse_args()
    banks = defaultdict(list)
    for row in rows([ROOT / path for path in args.inputs]):
        for name in categories(row):
            banks[name].append(row)
    required = {
        "turn_two_munkidori_attachment", "adrena_brain_own_damage_source",
        "shadow_bullet_ready", "shadow_bullet_conversion",
        "poke_pad_and_search_composition", "evolution_recovery_draw_sequencing",
    }
    missing = required - set(banks)
    if missing:
        raise RuntimeError(f"missing high-leverage mirror slices: {sorted(missing)}")
    output = ROOT / args.output_root
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"status": "complete", "feature_version": 5, "training_eligible": False, "slices": {}}
    for name in sorted(required):
        path = output / f"{name}.jsonl.gz"
        ordered = sorted(banks[name], key=lambda row: (str(row["episode_id"]), int(row["seat"]), int(row["step"])))
        with deterministic_gzip_text(path) as handle:
            for row in ordered:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        manifest["slices"][name] = {
            "rows": len(ordered),
            "episodes": len({str(row["episode_id"]) for row in ordered}),
            "actual_order": dict(Counter(str(row.get("hero_order") or "unknown") for row in ordered)),
            "path": str(path.resolve()), "sha256": sha256_file(path),
        }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
