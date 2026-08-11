#!/usr/bin/env python3
"""Build deterministic elite-refresh corpora from the August 4 schema-2 replay bank.

The builder deliberately keeps the identity view, the leakage-free top-20
episode split, and the rank-21--100 repair experiment as separate artifacts.
That makes it difficult to accidentally train on the identity/holdout rows.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import sys
import tarfile
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

from ptcg_ai.features import DecisionFeatures  # noqa: E402
from ptcg_ai.model import NumpyPolicyModel  # noqa: E402
from training.lucario_data import (  # noqa: E402
    canonical_deck,
    deterministic_gzip_text,
    load_deck,
    sha256_file,
)


EXPECTED_A2_SHA256 = "b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8"
EXPECTED_A2_ARCHIVE_SHA256 = "0958bd8847266efbc38658d62b9ac4dcd62a9aaed3d1098f093a677afcbfed4c"
FEATURE_VERSION = 2
DEFAULT_SEED = 20260811
RANK21_100_REHEARSAL_MULTIPLIER = 0.25

OUTPUT_NAMES = {
    "rank21_100_train": "rank21_100_train.jsonl.gz",
    "rank21_100_top3_repair_train": "rank21_100_top3_repair_train.jsonl.gz",
    "rank1_20_identity_validation": "rank1_20_identity_validation.jsonl.gz",
    "rank1_20_episode_train": "rank1_20_episode_train.jsonl.gz",
    "rank1_20_episode_holdout": "rank1_20_episode_holdout.jsonl.gz",
    "rank1_100_episode_train_rehearsal": "rank1_100_episode_train_rehearsal.jsonl.gz",
}


def _display_path(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _json_line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def _iter_rows(path: Path) -> Iterator[tuple[int, dict]]:
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"row is not an object at {path}:{line_number}")
            yield line_number, row


def _archive_member_sha256(path: Path, member: str) -> str:
    digest = hashlib.sha256()
    with tarfile.open(path, "r:gz") as archive:
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ValueError(f"archive member is not a regular file: {member}")
        for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_team_ranks(path: Path) -> tuple[dict[str, int], list[str]]:
    names = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(names) < 100:
        raise ValueError(f"team rank file must contain at least 100 names, found {len(names)}")
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise ValueError(f"team rank file contains duplicate names: {duplicates}")
    return {name: rank for rank, name in enumerate(names, 1)}, names


def row_key(row: dict) -> tuple[str, int, int]:
    episode_id = str(row.get("episode_id", ""))
    if not episode_id:
        raise ValueError("row has an empty episode_id")
    try:
        return episode_id, int(row["seat"]), int(row["step"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"row {episode_id!r} has an invalid seat or step") from exc


def validate_row(row: dict, expected_deck: tuple[int, ...], *, line_number: int) -> None:
    prefix = f"input row {line_number}"
    try:
        actual_deck = canonical_deck(row["deck"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{prefix} has an invalid deck") from exc
    if actual_deck != expected_deck:
        raise ValueError(f"{prefix} does not use the exact Grim deck")
    features = row.get("features")
    if not isinstance(features, dict) or int(features.get("feature_version", 1)) != FEATURE_VERSION:
        raise ValueError(f"{prefix} is not feature schema v{FEATURE_VERSION}")
    options = features.get("options")
    if not isinstance(options, list):
        raise ValueError(f"{prefix} has invalid feature options")
    action = row.get("action")
    if not isinstance(action, list) or any(type(index) is not int for index in action):
        raise ValueError(f"{prefix} has an invalid action")
    if len(action) != len(set(action)) or any(index < 0 or index >= len(options) for index in action):
        raise ValueError(f"{prefix} selects an invalid or duplicate option")
    team = row.get("team")
    if not isinstance(team, str) or not team:
        raise ValueError(f"{prefix} has an empty team")
    try:
        reward = float(row["reward"])
        weight = float(row.get("sample_weight", 1.0))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{prefix} has an invalid reward or sample_weight") from exc
    if not math.isfinite(reward) or reward <= 0:
        raise ValueError(f"{prefix} is not a winning elite decision")
    if not math.isfinite(weight) or weight <= 0:
        raise ValueError(f"{prefix} has a non-positive sample_weight")
    row_key(row)


def stable_episode_order(episode_id: str, seed: int) -> tuple[str, str]:
    digest = hashlib.sha256(f"{seed}:{episode_id}".encode("utf-8")).hexdigest()
    return digest, episode_id


def assign_top20_episode_splits(episode_ids, seed: int = DEFAULT_SEED) -> dict[str, str]:
    """Return an exact, deterministic whole-episode 80/20 train/holdout split."""
    unique = sorted({str(value) for value in episode_ids})
    if not unique:
        raise ValueError("no rank-1--20 episodes were observed")
    ordered = sorted(unique, key=lambda value: stable_episode_order(value, seed))
    holdout_count = round(len(ordered) * 0.20)
    if len(ordered) >= 2:
        holdout_count = min(len(ordered) - 1, max(1, holdout_count))
    else:
        holdout_count = 0
    holdout = set(ordered[:holdout_count])
    return {episode_id: "holdout" if episode_id in holdout else "train" for episode_id in unique}


def repair_weight_class(action: list[int], ranked: list[int]) -> tuple[str, float]:
    if len(action) != 1:
        return "outside_top3_or_multi", 1.0
    label = action[0]
    if ranked and ranked[0] == label:
        return "baseline_top1_correct", 0.5
    if label in ranked[:3]:
        return "label_in_top3_not_top1", 3.0
    return "outside_top3_or_multi", 1.0


@dataclass
class MetricBucket:
    records: int = 0
    single_action: int = 0
    multi_action: int = 0
    top1: int = 0
    top3: int = 0
    eligible_ge4: int = 0
    eligible_ge4_top1: int = 0
    eligible_ge4_top3: int = 0

    def update(self, action: list[int], ranked: list[int], option_count: int) -> None:
        self.records += 1
        if len(action) != 1:
            self.multi_action += 1
            return
        self.single_action += 1
        label = action[0]
        top1 = bool(ranked and ranked[0] == label)
        top3 = label in ranked[:3]
        self.top1 += int(top1)
        self.top3 += int(top3)
        if option_count >= 4:
            self.eligible_ge4 += 1
            self.eligible_ge4_top1 += int(top1)
            self.eligible_ge4_top3 += int(top3)

    def finalize(self) -> dict:
        return {
            "records": self.records,
            "single_action": self.single_action,
            "multi_action": self.multi_action,
            "top1_count": self.top1,
            "top3_count": self.top3,
            "top1_rate": self.top1 / max(1, self.single_action),
            "top3_rate": self.top3 / max(1, self.single_action),
            "eligible_options_ge4": {
                "single_action": self.eligible_ge4,
                "top1_count": self.eligible_ge4_top1,
                "top3_count": self.eligible_ge4_top3,
                "top1_rate": self.eligible_ge4_top1 / max(1, self.eligible_ge4),
                "top3_rate": self.eligible_ge4_top3 / max(1, self.eligible_ge4),
            },
        }


@dataclass
class OutputStats:
    rows: int = 0
    weight_sum: float = 0.0
    episodes: set[str] = field(default_factory=set)
    teams: Counter = field(default_factory=Counter)
    repair_classes: Counter = field(default_factory=Counter)

    def update(self, row: dict, repair_class: str | None = None) -> None:
        self.rows += 1
        self.weight_sum += float(row.get("sample_weight", 1.0))
        self.episodes.add(str(row["episode_id"]))
        self.teams[str(row["team"])] += 1
        if repair_class:
            self.repair_classes[repair_class] += 1

    def finalize(self) -> dict:
        result = {
            "rows": self.rows,
            "episodes": len(self.episodes),
            "teams": len(self.teams),
            "weight_sum": self.weight_sum,
            "rows_per_team": dict(sorted(self.teams.items())),
        }
        if self.repair_classes:
            result["repair_weight_classes"] = dict(sorted(self.repair_classes.items()))
        return result


@dataclass
class TeamStats:
    rank: int
    rows: int = 0
    episodes: set[str] = field(default_factory=set)
    top20_split_rows: Counter = field(default_factory=Counter)
    metrics: MetricBucket = field(default_factory=MetricBucket)

    def finalize(self) -> dict:
        return {
            "rank": self.rank,
            "rows": self.rows,
            "episodes": len(self.episodes),
            "top20_episode_split_rows": dict(sorted(self.top20_split_rows.items())),
            "a2": self.metrics.finalize(),
        }


def _rank_options(model, row: dict) -> list[int]:
    features = DecisionFeatures.from_json(row["features"])
    logits, _, _ = model.predict(features)
    if len(logits) != len(features.options):
        raise ValueError(
            f"A2 returned {len(logits)} logits for {len(features.options)} options at {row_key(row)}"
        )
    return np.argsort(-np.asarray(logits)).astype(int).tolist()


def _verified_provenance(a2_path: Path, archive_path: Path, verify: bool) -> dict:
    a2_sha = sha256_file(a2_path)
    archive_sha = sha256_file(archive_path) if archive_path.exists() else None
    member_sha = _archive_member_sha256(archive_path, "policy_weights.npz") if archive_path.exists() else None
    if verify:
        if a2_sha != EXPECTED_A2_SHA256:
            raise ValueError(f"A2 model hash mismatch: {a2_sha}")
        if archive_sha != EXPECTED_A2_ARCHIVE_SHA256:
            raise ValueError(f"authentic A2 archive hash mismatch: {archive_sha}")
        if member_sha != EXPECTED_A2_SHA256:
            raise ValueError(f"authentic archive A2 member hash mismatch: {member_sha}")
    return {
        "verification_required": verify,
        "expected_model_sha256": EXPECTED_A2_SHA256,
        "model_path": _display_path(a2_path),
        "model_sha256": a2_sha,
        "archive_path": _display_path(archive_path),
        "expected_archive_sha256": EXPECTED_A2_ARCHIVE_SHA256,
        "archive_sha256": archive_sha,
        "archive_member": "policy_weights.npz",
        "archive_member_sha256": member_sha,
        "verified": (
            a2_sha == EXPECTED_A2_SHA256
            and archive_sha == EXPECTED_A2_ARCHIVE_SHA256
            and member_sha == EXPECTED_A2_SHA256
        ),
    }


def build_elite_refresh(
    *,
    input_path: Path,
    team_ranks_path: Path,
    deck_path: Path,
    a2_path: Path,
    a2_archive_path: Path,
    output_dir: Path,
    seed: int = DEFAULT_SEED,
    include_rehearsal: bool = True,
    verify_a2: bool = True,
    model=None,
) -> dict:
    input_path = input_path.resolve()
    team_ranks_path = team_ranks_path.resolve()
    deck_path = deck_path.resolve()
    a2_path = a2_path.resolve()
    a2_archive_path = a2_archive_path.resolve()
    output_dir = output_dir.resolve()
    for required in (input_path, team_ranks_path, deck_path, a2_path):
        if not required.is_file():
            raise FileNotFoundError(required)
    if verify_a2 and not a2_archive_path.is_file():
        raise FileNotFoundError(a2_archive_path)

    expected_deck = load_deck(deck_path)
    if len(expected_deck) != 60:
        raise ValueError(f"exact Grim deck must contain 60 cards, found {len(expected_deck)}")
    rank_by_team, ranked_names = load_team_ranks(team_ranks_path)
    provenance = _verified_provenance(a2_path, a2_archive_path, verify_a2)
    if model is None:
        model = NumpyPolicyModel(a2_path)
    if getattr(model, "feature_version", FEATURE_VERSION) != FEATURE_VERSION:
        raise ValueError(f"A2 model is not feature schema v{FEATURE_VERSION}")

    input_rows = 0
    top20_episode_ids: set[str] = set()
    raw_rank_rows = Counter()
    for line_number, row in _iter_rows(input_path):
        input_rows += 1
        validate_row(row, expected_deck, line_number=line_number)
        rank = rank_by_team.get(row["team"])
        if rank is None or rank > 100:
            raw_rank_rows["outside_top100"] += 1
        elif rank <= 20:
            raw_rank_rows["rank1_20"] += 1
            top20_episode_ids.add(str(row["episode_id"]))
        else:
            raw_rank_rows["rank21_100"] += 1
    episode_splits = assign_top20_episode_splits(top20_episode_ids, seed)

    selected_names = list(OUTPUT_NAMES)
    if not include_rehearsal:
        selected_names.remove("rank1_100_episode_train_rehearsal")
    output_dir.mkdir(parents=True, exist_ok=True)
    final_paths = {name: output_dir / OUTPUT_NAMES[name] for name in selected_names}
    temporary_paths = {name: path.with_name(path.name + ".tmp") for name, path in final_paths.items()}
    for temporary in temporary_paths.values():
        if temporary.exists():
            temporary.unlink()

    output_stats = {name: OutputStats() for name in selected_names}
    source_metrics = {
        "rank1_20": MetricBucket(),
        "rank21_100": MetricBucket(),
        "rank1_20_episode_train": MetricBucket(),
        "rank1_20_episode_holdout": MetricBucket(),
    }
    team_stats: dict[str, TeamStats] = {}
    duplicate_rows = 0
    duplicate_conflicts = 0
    seen: dict[tuple[str, int, int], str] = {}

    def write(handles, name: str, row: dict, repair_class: str | None = None) -> None:
        handles[name].write(_json_line(row))
        output_stats[name].update(row, repair_class)

    try:
        with ExitStack() as stack:
            handles = {
                name: stack.enter_context(deterministic_gzip_text(temporary))
                for name, temporary in temporary_paths.items()
            }
            for line_number, row in _iter_rows(input_path):
                validate_row(row, expected_deck, line_number=line_number)
                rank = rank_by_team.get(row["team"])
                if rank is None or rank > 100:
                    continue
                key = row_key(row)
                row_digest = hashlib.sha256(_json_line(row).encode("utf-8")).hexdigest()
                prior = seen.get(key)
                if prior is not None:
                    if prior != row_digest:
                        duplicate_conflicts += 1
                        raise ValueError(f"conflicting duplicate decision key: {key}")
                    duplicate_rows += 1
                    continue
                seen[key] = row_digest

                action = row["action"]
                option_count = len(row["features"]["options"])
                ranked = _rank_options(model, row) if len(action) == 1 else []
                source_name = "rank1_20" if rank <= 20 else "rank21_100"
                source_metrics[source_name].update(action, ranked, option_count)
                current_team = team_stats.setdefault(row["team"], TeamStats(rank=rank))
                current_team.rows += 1
                current_team.episodes.add(str(row["episode_id"]))
                current_team.metrics.update(action, ranked, option_count)

                if rank <= 20:
                    split = episode_splits[str(row["episode_id"])]
                    current_team.top20_split_rows[split] += 1
                    source_metrics[f"rank1_20_episode_{split}"].update(action, ranked, option_count)

                    identity = dict(row)
                    identity["split"] = "validation"
                    write(handles, "rank1_20_identity_validation", identity)

                    split_row = dict(row)
                    split_row["split"] = split
                    write(handles, f"rank1_20_episode_{split}", split_row)
                    if include_rehearsal and split == "train":
                        rehearsal = dict(row)
                        rehearsal["split"] = "train"
                        write(handles, "rank1_100_episode_train_rehearsal", rehearsal)
                else:
                    baseline = dict(row)
                    baseline["split"] = "train"
                    write(handles, "rank21_100_train", baseline)

                    repair_class, multiplier = repair_weight_class(action, ranked)
                    repair = dict(baseline)
                    repair["sample_weight"] = float(row.get("sample_weight", 1.0)) * multiplier
                    write(handles, "rank21_100_top3_repair_train", repair, repair_class)
                    if include_rehearsal:
                        rehearsal = dict(baseline)
                        rehearsal["sample_weight"] = (
                            float(row.get("sample_weight", 1.0)) * RANK21_100_REHEARSAL_MULTIPLIER
                        )
                        write(handles, "rank1_100_episode_train_rehearsal", rehearsal)
        for name in selected_names:
            temporary_paths[name].replace(final_paths[name])
    except Exception:
        for temporary in temporary_paths.values():
            if temporary.exists():
                temporary.unlink()
        raise

    train_episodes = sorted(key for key, value in episode_splits.items() if value == "train")
    holdout_episodes = sorted(key for key, value in episode_splits.items() if value == "holdout")
    observed_teams = set(team_stats)
    manifest_outputs = {}
    for name, path in final_paths.items():
        manifest_outputs[name] = {
            "path": _display_path(path),
            "sha256": sha256_file(path),
            **output_stats[name].finalize(),
        }

    manifest = {
        "version": 1,
        "kind": "deterministic_elite_refresh_schema2",
        "inputs": {
            "decisions": {
                "path": _display_path(input_path),
                "sha256": sha256_file(input_path),
                "rows": input_rows,
            },
            "team_ranks": {
                "path": _display_path(team_ranks_path),
                "sha256": sha256_file(team_ranks_path),
                "names": len(ranked_names),
            },
            "exact_grim_deck": {
                "path": _display_path(deck_path),
                "sha256": sha256_file(deck_path),
                "cards": len(expected_deck),
                "canonical_card_sha256": hashlib.sha256(
                    ",".join(map(str, expected_deck)).encode("utf-8")
                ).hexdigest(),
            },
            "a2": provenance,
        },
        "rules": {
            "feature_version": FEATURE_VERSION,
            "exact_deck_only": True,
            "winning_rows_only": True,
            "deduplication_key": ["episode_id", "seat", "step"],
            "deduplication": "identical duplicates are skipped; conflicting duplicates fail closed",
            "a2_ranking": "numpy argsort of descending raw A2 logits; no tactical rails",
            "a2_metrics": "single-action labels only; eligible_options_ge4 additionally requires >=4 options",
            "top3_repair_weights": {
                "baseline_top1_correct": 0.5,
                "label_in_top3_not_top1": 3.0,
                "outside_top3_or_multi": 1.0,
                "operation": "multiply the source sample_weight",
            },
            "identity_validation": "all unique rank-1--20 decisions; diagnostic only",
            "top20_split": "whole episodes; exact rounded 80/20 by seeded SHA-256 order",
            "top20_split_seed": seed,
            "rehearsal": (
                "rank-1--20 episode-train rows at source weight plus rank-21--100 rehearsal rows"
                if include_rehearsal else "not generated"
            ),
            "rank21_100_rehearsal_multiplier": (
                RANK21_100_REHEARSAL_MULTIPLIER if include_rehearsal else None
            ),
        },
        "counts": {
            "input_rows": input_rows,
            "raw_rank_rows": dict(sorted(raw_rank_rows.items())),
            "unique_selected_rows": len(seen),
            "identical_duplicate_rows_skipped": duplicate_rows,
            "conflicting_duplicate_rows": duplicate_conflicts,
            "observed_top100_teams": len(observed_teams),
        },
        "top20_episode_split": {
            "episodes": len(episode_splits),
            "train_episodes": len(train_episodes),
            "holdout_episodes": len(holdout_episodes),
            "actual_train_fraction": len(train_episodes) / max(1, len(episode_splits)),
            "train_episode_ids": train_episodes,
            "holdout_episode_ids": holdout_episodes,
            "overlap": sorted(set(train_episodes) & set(holdout_episodes)),
        },
        "a2_metrics": {name: bucket.finalize() for name, bucket in sorted(source_metrics.items())},
        "per_team": {name: stats.finalize() for name, stats in sorted(team_stats.items())},
        "rank_coverage": {
            "observed": [
                {"rank": rank_by_team[name], "team": name}
                for name in sorted(observed_teams, key=lambda value: rank_by_team[value])
            ],
            "missing_from_input_top100": [
                {"rank": rank, "team": name}
                for rank, name in enumerate(ranked_names[:100], 1)
                if name not in observed_teams
            ],
        },
        "outputs": manifest_outputs,
    }
    manifest_path = output_dir / "manifest.json"
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".tmp")
    temporary_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_manifest.replace(manifest_path)
    return manifest


def _resolve(path: str) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="data/daily_extracted/2026-08-04_decisions.jsonl.gz")
    parser.add_argument("--team-ranks", default="data/top_teams_20260804.txt")
    parser.add_argument("--deck", default="freshstart/decklists/grimmsnarl_marnie.deck.csv")
    parser.add_argument("--a2", default="artifacts/recovery_probes/extracted/a2/policy_weights.npz")
    parser.add_argument("--a2-archive", default="artifacts/recovery_probes/a2_v2_shield.tar.gz")
    parser.add_argument("--output-dir", default="artifacts/elite_refresh_20260804")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--no-rehearsal-variant", action="store_true")
    args = parser.parse_args()

    manifest = build_elite_refresh(
        input_path=_resolve(args.input),
        team_ranks_path=_resolve(args.team_ranks),
        deck_path=_resolve(args.deck),
        a2_path=_resolve(args.a2),
        a2_archive_path=_resolve(args.a2_archive),
        output_dir=_resolve(args.output_dir),
        seed=args.seed,
        include_rehearsal=not args.no_rehearsal_variant,
    )
    summary = {
        "manifest": _display_path(_resolve(args.output_dir) / "manifest.json"),
        "unique_selected_rows": manifest["counts"]["unique_selected_rows"],
        "top20_episodes": manifest["top20_episode_split"]["episodes"],
        "a2_rank1_20": manifest["a2_metrics"]["rank1_20"],
        "a2_rank21_100": manifest["a2_metrics"]["rank21_100"],
        "outputs": {
            name: {key: value for key, value in row.items() if key in {"path", "rows", "sha256"}}
            for name, row in manifest["outputs"].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
