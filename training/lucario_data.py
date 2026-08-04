#!/usr/bin/env python3
"""Build an audited, leakage-free exact-deck replay view.

The original consumer is the two-variant Lucario curriculum. The same builder
also supports a single sparse matchup deck so every specialist bootstrap uses
identical split, deduplication, and sample-weighting rules.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
import zlib
from collections import Counter, defaultdict
from pathlib import Path


def canonical_deck(cards) -> tuple[int, ...]:
    return tuple(sorted(int(card) for card in cards))


def load_deck(path: str | Path) -> tuple[int, ...]:
    return canonical_deck(line for line in Path(path).read_text().splitlines() if line.strip())


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextlib.contextmanager
def deterministic_gzip_text(path: str | Path):
    """Write gzip text with a fixed header timestamp for reproducible hashes."""
    with Path(path).open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8") as handle:
                yield handle


def stable_order(seed: int, episode_id) -> str:
    return hashlib.sha256(f"{seed}:{episode_id}".encode("utf-8")).hexdigest()


def assign_episode_splits(episodes: list[dict], seed: int = 20260803) -> dict[str, str]:
    """Stratify by variant and outcome, assigning whole episodes to one split."""
    strata: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for episode in episodes:
        strata[(episode["variant"], int(episode["reward"] > 0))].append(episode)
    assignments: dict[str, str] = {}
    for values in strata.values():
        ordered = sorted(values, key=lambda row: stable_order(seed, row["episode_id"]))
        if len(ordered) < 3:
            raise ValueError("each variant/outcome stratum needs at least three episodes")
        validation_count = max(1, round(len(ordered) * 0.15))
        holdout_count = max(1, round(len(ordered) * 0.15))
        while validation_count + holdout_count >= len(ordered):
            if holdout_count > 1:
                holdout_count -= 1
            elif validation_count > 1:
                validation_count -= 1
            else:
                raise ValueError("cannot retain a training episode in stratum")
        for index, episode in enumerate(ordered):
            split = "holdout" if index < holdout_count else "validation" if index < holdout_count + validation_count else "train"
            assignments[str(episode["episode_id"])] = split
    return assignments


def episode_group(episode: dict) -> str:
    """Return the leakage boundary used by the audited Lucario splits."""
    return str(episode.get("team") or episode.get("submission_id") or episode["episode_id"])


def assign_grouped_splits(episodes: list[dict], seed: int = 20260803) -> dict[str, str]:
    """Assign whole teams to unseen, temporal, validation, or training splits.

    The newest 15% of non-unseen groups are temporal. A stable 10% crc32 bucket
    is the unseen-team holdout, and 15% of the remainder is internal validation.
    Small corpora retain at least one training group whenever possible.
    """
    if not episodes:
        raise ValueError("exact-deck replay view is empty")
    groups: dict[str, list[dict]] = defaultdict(list)
    for episode in episodes:
        groups[episode_group(episode)].append(episode)
    names = sorted(groups)
    if len(names) < 4:
        return assign_episode_splits(episodes, seed)

    unseen = {name for name in names if zlib.crc32(name.encode("utf-8")) % 10 == 0}
    if not unseen:
        unseen = {min(names, key=lambda name: stable_order(seed + 1, name))}
    if len(unseen) >= len(names) - 2:
        unseen = {min(unseen, key=lambda name: stable_order(seed + 1, name))}

    remaining = [name for name in names if name not in unseen]
    newest = sorted(
        remaining,
        key=lambda name: max(str(row.get("created_at", "")) for row in groups[name]),
        reverse=True,
    )
    temporal_count = max(1, round(len(remaining) * 0.15))
    temporal = set(newest[:temporal_count])
    remaining = [name for name in remaining if name not in temporal]
    validation_count = max(1, round(len(remaining) * 0.15))
    validation = set(sorted(remaining, key=lambda name: stable_order(seed + 2, name))[:validation_count])

    group_split = {
        name: "unseen_team" if name in unseen else
        "temporal" if name in temporal else
        "validation" if name in validation else "train"
        for name in names
    }
    return {
        str(episode["episode_id"]): group_split[episode_group(episode)]
        for episode in episodes
    }


def summarize(episodes: list[dict], decisions: Counter) -> dict:
    result = {}
    for variant in sorted({row["variant"] for row in episodes}):
        result[variant] = {}
        for split in ("train", "validation", "unseen_team", "temporal", "holdout"):
            selected = [row for row in episodes if row["variant"] == variant and row["split"] == split]
            result[variant][split] = {
                "episodes": len(selected),
                "wins": sum(int(row["reward"] > 0) for row in selected),
                "decisions": sum(decisions[(str(row["episode_id"]), variant)] for row in selected),
            }
    return result


def build_replay_view(
    source: str | Path | list[str | Path],
    deck_paths: list[str | Path],
    output: str | Path,
    manifest_path: str | Path,
    seed: int = 20260803,
) -> dict:
    if not deck_paths:
        raise ValueError("at least one exact deck signature is required")
    signatures = {f"variant_{index + 1}": load_deck(path) for index, path in enumerate(deck_paths)}
    if len(set(signatures.values())) != len(signatures):
        raise ValueError("exact deck variants must have distinct signatures")
    signature_names = {signature: name for name, signature in signatures.items()}

    sources = [source] if isinstance(source, (str, Path)) else list(source)
    if not sources:
        raise ValueError("at least one exact-deck replay source is required")
    selected_rows = []
    episode_meta = {}
    seen = set()
    duplicate_records = 0
    for source_path in map(Path, sources):
        with gzip.open(source_path, "rt", encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                variant = signature_names.get(canonical_deck(row.get("deck", [])))
                if variant is None:
                    continue
                key = (str(row["episode_id"]), int(row.get("seat", -1)), int(row["step"]))
                if key in seen:
                    duplicate_records += 1
                    continue
                seen.add(key)
                episode_key = f"{row['episode_id']}:{int(row.get('seat', -1))}"
                reward = float(row["reward"])
                metadata = {
                    "episode_id": episode_key, "source_episode_id": row["episode_id"],
                    "seat": int(row.get("seat", -1)), "variant": variant, "reward": reward,
                    "team": row.get("team", ""), "submission_id": row.get("submission_id"),
                    "created_at": row.get("created_at", ""),
                }
                previous = episode_meta.setdefault(episode_key, metadata)
                if previous["variant"] != variant or previous["reward"] != reward:
                    raise ValueError(f"inconsistent metadata for episode {episode_key}")
                selected_rows.append((row, variant))
    # A Lucario mirror exposes both sides of the same game with opposite rewards.
    # Retain one deterministic seat so an episode can never leak across splits.
    seats_by_source: dict[str, list[str]] = defaultdict(list)
    for unit_key, episode in episode_meta.items():
        seats_by_source[str(episode["source_episode_id"])].append(unit_key)
    retained_units = {
        min(units, key=lambda key: stable_order(seed + 99, key))
        for units in seats_by_source.values()
    }
    dual_episode_seats_removed = sum(max(0, len(units) - 1) for units in seats_by_source.values())
    selected_rows = [
        (row, variant) for row, variant in selected_rows
        if f"{row['episode_id']}:{int(row.get('seat', -1))}" in retained_units
    ]
    episode_meta = {key: value for key, value in episode_meta.items() if key in retained_units}
    episodes = list(episode_meta.values())
    assignments = assign_grouped_splits(episodes, seed)
    for episode in episodes:
        episode["split"] = assignments[str(episode["episode_id"])]

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    decision_counts = Counter()
    train_counts = Counter()
    for row, variant in selected_rows:
        unit_key = f"{row['episode_id']}:{int(row.get('seat', -1))}"
        if assignments[unit_key] == "train":
            context = str(row.get("features", {}).get("options", [{}])[0].get("context", -1))
            train_counts[(variant, int(float(row["reward"]) > 0), int(row.get("seat", -1)), str(row.get("team", "")), context)] += 1
    normalizer_terms = []
    for row, variant in selected_rows:
        unit_key = f"{row['episode_id']}:{int(row.get('seat', -1))}"
        if assignments[unit_key] == "train":
            context = str(row.get("features", {}).get("options", [{}])[0].get("context", -1))
            key = (variant, int(float(row["reward"]) > 0), int(row.get("seat", -1)), str(row.get("team", "")), context)
            normalizer_terms.append((1.25 if float(row["reward"]) > 0 else 1.0) / train_counts[key])
    mean_weight = sum(normalizer_terms) / max(1, len(normalizer_terms))

    with deterministic_gzip_text(temporary) as handle:
        for row, variant in selected_rows:
            episode_key = f"{row['episode_id']}:{int(row.get('seat', -1))}"
            enriched = dict(row)
            enriched["lucario_variant"] = variant
            enriched["split"] = assignments[episode_key]
            if enriched["split"] == "train":
                context = str(row.get("features", {}).get("options", [{}])[0].get("context", -1))
                balance_key = (variant, int(float(row["reward"]) > 0), int(row.get("seat", -1)), str(row.get("team", "")), context)
                raw_weight = (1.25 if float(row["reward"]) > 0 else 1.0) / train_counts[balance_key]
                enriched["sample_weight"] = raw_weight / max(mean_weight, 1e-12)
            handle.write(json.dumps(enriched, separators=(",", ":")) + "\n")
            decision_counts[(episode_key, variant)] += 1
    os.replace(temporary, output)

    manifest = {
        "version": 1,
        "sources": [{"path": str(path), "sha256": sha256_file(path)} for path in map(Path, sources)],
        "output": str(output),
        "output_sha256": sha256_file(output),
        "split_seed": seed,
        "episodes": len(episodes),
        "decisions": len(selected_rows),
        "duplicate_records_removed": duplicate_records,
        "dual_episode_seats_removed": dual_episode_seats_removed,
        "variants": {
            name: {
                "deck": str(Path(deck_paths[index])),
                "deck_sha256": sha256_file(deck_paths[index]),
                "signature": list(signature),
            }
            for index, (name, signature) in enumerate(signatures.items())
        },
        "coverage": summarize(episodes, decision_counts),
        "episode_assignments": {key: assignments[key] for key in sorted(assignments)},
        "split_groups": {
            split: sorted({episode_group(row) for row in episodes if assignments[str(row["episode_id"])] == split})
            for split in ("train", "validation", "unseen_team", "temporal", "holdout")
        },
    }
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.replace(temporary_manifest, manifest_path)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--deck", action="append", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--seed", type=int, default=20260803)
    args = parser.parse_args()
    manifest = build_replay_view(args.source, args.deck, args.output, args.manifest, args.seed)
    print(json.dumps({key: manifest[key] for key in ("episodes", "decisions", "coverage")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
