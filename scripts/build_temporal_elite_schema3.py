#!/usr/bin/env python3
"""Build a deterministic Aug-4/5 train and Aug-6 elite Grim holdout corpus."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if (ROOT / "vendor").exists():
    sys.path.insert(0, str(ROOT / "vendor"))

import numpy as np

from ptcg_ai.features import DecisionFeatures, V2_GLOBAL_SIZE, V3_OPTION_NUMERIC_SIZE
from ptcg_ai.model import NumpyPolicyModel
from training.lucario_data import canonical_deck, deterministic_gzip_text, load_deck, sha256_file
from training.schema3 import pad_schema3


DATES = ("2026-08-04", "2026-08-05", "2026-08-06")
TRAIN_DATES = frozenset(DATES[:2])
HOLDOUT_DATE = DATES[2]
EXPECTED_A2_SHA256 = "b19871a9f1499c2460ae266e58194acab1d8c90b390fa5cf24ed94b9a2b6bda8"
EXPECTED_PADDED_A2_SHA256 = "80a0ef14d00256f2718d23e8323544b2901a7df1a9caafd5070ed0b4b9779acc"
EXPECTED_RANKING_SHA256 = "b116af00e28241269f1dfdec232e2d6dc33891a4df4ca52583beed7d307ff20f"
EXPECTED_DECK_SHA256 = "48f1a03e8ab8162f6dc608e6743a4f3b32004cb702ca447050e62055b85defbf"
FROZEN_INPUTS = {
    "2026-08-04": {
        "shard": "cd202bdfbd813f99df19a751fc2ad9053f3beb5316bfa7e652c8dce61fef19ba",
        "manifest": "bc4e72db7198cab9e4d5bbd9c72136310ca5433577543be2000e6847d3dd345c",
    },
    "2026-08-05": {
        "shard": "9c034fc27bfd391acf6f774ded92474b8f9246ea37c0e6dba00d9a394a3ff4c0",
        "manifest": "f7297f93229e5fcf9ad66a16d3fb2b1a82383ac6fc32b5163d8a8cfd212c2c1f",
    },
    "2026-08-06": {
        "shard": "b95818ed961f85ab2cab9231014f58bda9a97e3d7a7de5d094ab4dbbfe0ce6a9",
        "manifest": "e5ba7b4317c9e76f3ba04e4df3bf4d85a4251bcb675f33594e20329998c96860",
    },
}
OUTPUT_FILES = {
    "train": "train_winners_aug4_aug5_rank1_100.jsonl.gz",
    "holdout": "holdout_winners_aug6_rank1_100.jsonl.gz",
    "hard_holdout": "holdout_winners_aug6_rank1_20.jsonl.gz",
}


def _display(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _json_line(row: Mapping[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"


def _digest_strings(values) -> str:
    payload = "\n".join(sorted(str(value) for value in values)) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def deck_digest(deck: tuple[int, ...]) -> str:
    return hashlib.sha256(",".join(map(str, deck)).encode("utf-8")).hexdigest()


def model_behavior_digest(path: Path) -> str:
    """Hash model arrays while normalizing a schema-3 all-zero padding row."""
    with np.load(path, allow_pickle=False) as arrays:
        version = int(np.asarray(arrays.get("model_schema_version", 1)).item())
        digest = hashlib.sha256()
        for name in sorted(item for item in arrays.files if item != "model_schema_version"):
            value = np.asarray(arrays[name])
            if name == "numeric_w" and version == 3:
                if value.shape[0] != V3_OPTION_NUMERIC_SIZE or np.count_nonzero(value[-1]):
                    raise ValueError("schema-3 A2 anchor is not an all-zero behavior-preserving pad")
                value = value[:-1]
            value = np.ascontiguousarray(value)
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(value.dtype.str.encode("ascii") + b"\0")
            digest.update(str(value.shape).encode("ascii") + b"\0")
            digest.update(value.tobytes())
    return digest.hexdigest()


def build_padded_anchor(source: Path, destination: Path, *, verify_frozen: bool) -> dict:
    source_hash = sha256_file(source)
    if verify_frozen and source_hash != EXPECTED_A2_SHA256:
        raise ValueError(f"frozen A2 hash mismatch: {source_hash}")
    with np.load(source, allow_pickle=False) as arrays:
        version = int(np.asarray(arrays.get("model_schema_version", 1)).item())
        if version != 2 or np.asarray(arrays["numeric_w"]).shape[0] != V3_OPTION_NUMERIC_SIZE - 1:
            raise ValueError("A2 source is not the expected schema-2 model")
    pad_schema3(source, destination)
    padded_hash = sha256_file(destination)
    if verify_frozen and padded_hash != EXPECTED_PADDED_A2_SHA256:
        raise ValueError(f"padded A2 hash mismatch: {padded_hash}")
    source_behavior = model_behavior_digest(source)
    padded_behavior = model_behavior_digest(destination)
    if source_behavior != padded_behavior:
        raise ValueError("schema-3 padding changed A2 behavior arrays")
    return {
        "source_path": _display(source),
        "source_sha256": source_hash,
        "source_schema": 2,
        "padded_path": _display(destination),
        "padded_sha256": padded_hash,
        "padded_schema": 3,
        "behavior_digest": source_behavior,
        "behavior_digest_equal": True,
        "migration": "append one all-zero attack-nullification numeric_w row; all other arrays unchanged",
    }


def load_ranking(path: Path, *, verify_frozen: bool) -> tuple[dict[str, int], list[str]]:
    if verify_frozen and sha256_file(path) != EXPECTED_RANKING_SHA256:
        raise ValueError("frozen Aug-4 team-ranking hash mismatch")
    names = [line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if len(names) != 100:
        raise ValueError(f"frozen Aug-4 ranking must contain exactly 100 teams, found {len(names)}")
    duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicates:
        raise ValueError(f"team ranking contains duplicates: {duplicates}")
    return {name: index for index, name in enumerate(names, 1)}, names


def discover_local_lineage(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    """Use explicit checked-in local-team labels plus the frozen leaderboard; never infer names."""
    script = root / "scripts" / "audit_grim_floor_director.py"
    leaderboards = sorted(root.glob("pokemon-tcg-ai-battle-publicleaderboard-2026-08-04*.csv"))
    if not script.is_file() or not leaderboards:
        return {}
    locally_named = set(re.findall(r'"local"\s*,\s*"([^"]+)"', script.read_text(encoding="utf-8")))
    if not locally_named:
        return {}
    leaderboard = leaderboards[-1]
    with leaderboard.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = {str(row.get("TeamName")): row for row in csv.DictReader(handle)}
    result = {}
    for name in sorted(locally_named & set(rows)):
        row = rows[name]
        result[name] = {
            "basis": "checked-in audit code explicitly labels this as local and the frozen leaderboard confirms it",
            "local_label_source": _display(script),
            "local_label_source_sha256": sha256_file(script),
            "leaderboard_source": _display(leaderboard),
            "leaderboard_source_sha256": sha256_file(leaderboard),
            "leaderboard_rank": int(row["Rank"]),
            "team_id": str(row["TeamId"]),
        }
    return result


def _iter_rows(path: Path) -> Iterator[tuple[int, dict]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"non-object row at {path}:{line_number}")
            yield line_number, row


def coordinate(row: Mapping[str, Any]) -> tuple[str, int, int]:
    episode = str(row.get("episode_id", "")).strip()
    if not episode:
        raise ValueError("row has an empty episode_id")
    try:
        seat = int(row["seat"])
        step = int(row["step"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"episode {episode} has an invalid seat or step") from exc
    if seat not in (0, 1) or step < 0:
        raise ValueError(f"episode {episode} has an invalid seat or step")
    return episode, seat, step


def validate_row(row: dict, *, date: str, exact_deck: tuple[int, ...], expected_deck_digest: str) -> None:
    episode, _seat, step = coordinate(row)
    prefix = f"{date} episode {episode} step {step}"
    if str(row.get("source_date")) != date:
        raise ValueError(f"{prefix}: source_date mismatch")
    if canonical_deck(row.get("deck", ())) != exact_deck:
        raise ValueError(f"{prefix}: exact Grim deck mismatch")
    if str(row.get("hero_deck_sha256", "")) != expected_deck_digest:
        raise ValueError(f"{prefix}: exact Grim deck digest mismatch")
    features = row.get("features")
    if not isinstance(features, dict) or int(features.get("feature_version", -1)) != 3:
        raise ValueError(f"{prefix}: expected feature schema 3")
    if not isinstance(features.get("global"), list) or len(features["global"]) != V2_GLOBAL_SIZE:
        raise ValueError(f"{prefix}: schema-3 global vector mismatch")
    if not isinstance(features.get("tokens"), list) or not isinstance(features.get("options"), list):
        raise ValueError(f"{prefix}: malformed schema-3 features")
    for option in features["options"]:
        if not isinstance(option, dict) or len(option.get("numeric", ())) != V3_OPTION_NUMERIC_SIZE:
            raise ValueError(f"{prefix}: schema-3 option width mismatch")
    action = row.get("action")
    if not isinstance(action, list) or any(type(value) is not int for value in action):
        raise ValueError(f"{prefix}: invalid action")
    if len(action) != len(set(action)) or any(value < 0 or value >= len(features["options"]) for value in action):
        raise ValueError(f"{prefix}: action is not a legal unique option selection")
    team = row.get("team")
    if not isinstance(team, str) or not team:
        raise ValueError(f"{prefix}: missing team")
    try:
        reward = float(row["reward"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{prefix}: invalid reward") from exc
    if not math.isfinite(reward):
        raise ValueError(f"{prefix}: non-finite reward")
    expected_outcome = "win" if reward > 0 else "loss"
    if row.get("outcome") != expected_outcome:
        raise ValueError(f"{prefix}: reward/outcome mismatch")


def _wilson(hits: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    p = hits / total
    scale = 1 + z * z / total
    center = (p + z * z / (2 * total)) / scale
    radius = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / scale
    return [center - radius, center + radius]


def _rate(hits: int, total: int) -> dict[str, Any]:
    return {
        "hits": hits,
        "total": total,
        "rate": hits / total if total else None,
        "wilson_95": _wilson(hits, total),
    }


@dataclass
class MetricBucket:
    records: int = 0
    single: int = 0
    multi: int = 0
    top1: int = 0
    top3: int = 0
    nonforced: int = 0
    nonforced_top1: int = 0
    top3_eligible: int = 0
    top3_eligible_hits: int = 0

    def update(self, action: list[int], ranking: list[int], option_count: int) -> None:
        self.records += 1
        if len(action) != 1:
            self.multi += 1
            return
        self.single += 1
        label = action[0]
        self.top1 += int(bool(ranking) and ranking[0] == label)
        self.top3 += int(label in ranking[:3])
        if option_count >= 2:
            self.nonforced += 1
            self.nonforced_top1 += int(ranking[0] == label)
        if option_count >= 4:
            self.top3_eligible += 1
            self.top3_eligible_hits += int(label in ranking[:3])

    def finalize(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "single_action_records": self.single,
            "multi_action_records": self.multi,
            "single_index_top1": _rate(self.top1, self.single),
            "single_index_top3": _rate(self.top3, self.single),
            "single_nonforced_top1_options_ge2": _rate(self.nonforced_top1, self.nonforced),
            "single_meaningful_top3_options_ge4": _rate(self.top3_eligible_hits, self.top3_eligible),
        }


@dataclass
class MetricReport:
    overall: MetricBucket = field(default_factory=MetricBucket)
    by_team: dict[str, MetricBucket] = field(default_factory=lambda: defaultdict(MetricBucket))
    by_option_count: dict[int, MetricBucket] = field(default_factory=lambda: defaultdict(MetricBucket))

    def update(self, row: dict, model: Any) -> None:
        features = DecisionFeatures.from_json(row["features"])
        action = [int(value) for value in row["action"]]
        ranking: list[int] = []
        if len(action) == 1:
            logits, _count_logits, _value = model.predict(features)
            if len(logits) != len(features.options):
                raise ValueError(f"A2 logit width mismatch at {coordinate(row)}")
            ranking = np.argsort(-np.asarray(logits)).astype(int).tolist()
        option_count = len(features.options)
        self.overall.update(action, ranking, option_count)
        self.by_team[str(row["team"])].update(action, ranking, option_count)
        self.by_option_count[option_count].update(action, ranking, option_count)

    def finalize(self, ranks: Mapping[str, int]) -> dict[str, Any]:
        return {
            "overall": self.overall.finalize(),
            "by_team": {
                team: {"aug4_rank": ranks[team], **bucket.finalize()}
                for team, bucket in sorted(self.by_team.items(), key=lambda item: ranks[item[0]])
            },
            "by_option_count": {
                str(count): bucket.finalize()
                for count, bucket in sorted(self.by_option_count.items())
            },
        }


@dataclass
class OutputStats:
    rows: int = 0
    episodes: set[str] = field(default_factory=set)
    units: set[tuple[str, int]] = field(default_factory=set)
    teams: set[str] = field(default_factory=set)

    def update(self, row: dict) -> None:
        episode, seat, _step = coordinate(row)
        self.rows += 1
        self.episodes.add(episode)
        self.units.add((episode, seat))
        self.teams.add(str(row["team"]))

    def finalize(self) -> dict[str, int]:
        return {
            "rows": self.rows,
            "episodes": len(self.episodes),
            "episode_seat_units": len(self.units),
            "teams": len(self.teams),
        }


def _source_audit(
    date: str,
    shard: Path,
    manifest_path: Path,
    *,
    verify_frozen: bool,
) -> tuple[dict, int]:
    shard_hash = sha256_file(shard)
    manifest_hash = sha256_file(manifest_path)
    if verify_frozen:
        expected = FROZEN_INPUTS[date]
        if shard_hash != expected["shard"] or manifest_hash != expected["manifest"]:
            raise ValueError(f"frozen {date} shard or manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "complete"
        or manifest.get("date") != date
        or int(manifest.get("feature_version", -1)) != 3
        or str(manifest.get("output_sha256", "")).lower() != shard_hash
    ):
        raise ValueError(f"{date} source manifest does not certify this schema-3 shard")
    expected_rows = int(manifest.get("decision_count", -1))
    if expected_rows <= 0:
        raise ValueError(f"{date} source manifest has no positive decision count")
    return {
        "shard_path": _display(shard),
        "shard_sha256": shard_hash,
        "manifest_path": _display(manifest_path),
        "manifest_sha256": manifest_hash,
        "archive_sha256": manifest.get("archive_sha256"),
        "manifest_decision_count": expected_rows,
        "feature_version": 3,
    }, expected_rows


def _normalized_row(row: dict, *, split: str, rank: int) -> dict:
    # Raw observations are present only in the Aug-4 regeneration and are not
    # model inputs. Removing them makes all three dates use one minimal schema.
    result = {key: value for key, value in row.items() if key != "observation"}
    result["split"] = split
    result["team_rank_aug4"] = rank
    return result


def build_temporal_elite_schema3(
    *,
    sources: Mapping[str, tuple[Path, Path]],
    ranking_path: Path,
    deck_path: Path,
    a2_path: Path,
    output_dir: Path,
    excluded_lineage: Mapping[str, Mapping[str, Any]] | None = None,
    verify_frozen: bool = True,
    model: Any | None = None,
) -> dict:
    if tuple(sources) != DATES:
        raise ValueError(f"sources must be in exact temporal order {DATES}")
    for shard, manifest in sources.values():
        if not shard.is_file() or not manifest.is_file():
            raise FileNotFoundError(shard if not shard.is_file() else manifest)
    for required in (ranking_path, deck_path, a2_path):
        if not required.is_file():
            raise FileNotFoundError(required)
    if verify_frozen and sha256_file(deck_path) != EXPECTED_DECK_SHA256:
        raise ValueError("frozen exact-Grim deck file hash mismatch")
    exact_deck = load_deck(deck_path)
    if len(exact_deck) != 60:
        raise ValueError(f"exact Grim deck must contain 60 cards, found {len(exact_deck)}")
    expected_deck_digest = deck_digest(exact_deck)
    ranks, ranked_teams = load_ranking(ranking_path, verify_frozen=verify_frozen)
    excluded_lineage = {str(key): dict(value) for key, value in (excluded_lineage or {}).items()}

    output_dir.mkdir(parents=True, exist_ok=True)
    final_paths = {name: output_dir / filename for name, filename in OUTPUT_FILES.items()}
    anchor_path = output_dir / "a2_schema3_zero_init.npz"
    metrics_path = output_dir / "a2_holdout_metrics.json"
    manifest_path = output_dir / "manifest.json"
    temporary_paths = {
        name: path.with_name(path.name + ".tmp") for name, path in final_paths.items()
    }
    anchor_temporary = output_dir / "a2_schema3_zero_init.tmp.npz"
    metrics_temporary = metrics_path.with_name(metrics_path.name + ".tmp")
    manifest_temporary = manifest_path.with_name(manifest_path.name + ".tmp")
    cleanup = [*temporary_paths.values(), anchor_temporary, metrics_temporary, manifest_temporary]
    for path in cleanup:
        if path.exists():
            path.unlink()

    try:
        anchor = build_padded_anchor(a2_path, anchor_temporary, verify_frozen=verify_frozen)
        metric_model = model if model is not None else NumpyPolicyModel(anchor_temporary)
        if int(getattr(metric_model, "feature_version", -1)) != 3:
            raise ValueError("A2 metric model must consume feature schema 3")

        source_reports = {}
        expected_source_rows = {}
        for date, (shard, source_manifest) in sources.items():
            source_reports[date], expected_source_rows[date] = _source_audit(
                date, shard, source_manifest, verify_frozen=verify_frozen
            )

        stats = {name: OutputStats() for name in OUTPUT_FILES}
        source_counts = {date: Counter() for date in DATES}
        metrics = MetricReport()
        hard_metrics = MetricReport()
        seen_selected: dict[tuple[str, int, int], str] = {}
        selected_duplicate_rows = 0
        episode_dates: dict[str, str] = {}
        unit_facts: dict[tuple[str, int], tuple] = {}
        train_episodes: set[str] = set()
        holdout_episodes: set[str] = set()
        hard_episodes: set[str] = set()
        heldout_keys: set[tuple[str, int, int]] = set()
        hard_keys: set[tuple[str, int, int]] = set()
        eligible_unique_by_unit = Counter()
        written_by_unit = Counter()

        with (
            deterministic_gzip_text(temporary_paths["train"]) as train_handle,
            deterministic_gzip_text(temporary_paths["holdout"]) as holdout_handle,
            deterministic_gzip_text(temporary_paths["hard_holdout"]) as hard_handle,
        ):
            for date, (shard, _source_manifest) in sources.items():
                counts = source_counts[date]
                for line_number, row in _iter_rows(shard):
                    counts["input_rows"] += 1
                    try:
                        validate_row(
                            row,
                            date=date,
                            exact_deck=exact_deck,
                            expected_deck_digest=expected_deck_digest,
                        )
                    except ValueError as exc:
                        raise ValueError(f"{shard}:{line_number}: {exc}") from exc
                    episode, seat, _step = coordinate(row)
                    prior_date = episode_dates.setdefault(episode, date)
                    if prior_date != date:
                        raise ValueError(f"episode overlap across source dates: {episode} ({prior_date}, {date})")
                    reward = float(row["reward"])
                    team = str(row["team"])
                    rank = ranks.get(team)
                    if team in excluded_lineage:
                        counts["known_lineage_rows_observed"] += 1
                    facts = (date, team, reward > 0, str(row["outcome"]), rank)
                    unit = (episode, seat)
                    prior_facts = unit_facts.setdefault(unit, facts)
                    if prior_facts != facts:
                        raise ValueError(f"inconsistent episode-seat facts: {unit}")
                    if reward <= 0:
                        counts["loss_rows_excluded"] += 1
                        continue
                    counts["winning_rows"] += 1
                    if team in excluded_lineage:
                        counts["known_lineage_winning_rows_excluded"] += 1
                        continue
                    if rank is None:
                        counts["winning_rows_outside_frozen_top100"] += 1
                        continue
                    counts["winning_rows_frozen_top100"] += 1

                    split = "train" if date in TRAIN_DATES else "temporal_holdout"
                    output_name = "train" if split == "train" else "holdout"
                    normalized = _normalized_row(row, split=split, rank=rank)
                    serialized = _json_line(normalized)
                    key = coordinate(row)
                    row_digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
                    prior_digest = seen_selected.get(key)
                    if prior_digest is not None:
                        if prior_digest != row_digest:
                            raise ValueError(f"conflicting duplicate episode/seat/step: {key}")
                        selected_duplicate_rows += 1
                        continue
                    seen_selected[key] = row_digest
                    eligible_unique_by_unit[unit] += 1

                    handle = train_handle if output_name == "train" else holdout_handle
                    handle.write(serialized)
                    stats[output_name].update(normalized)
                    written_by_unit[unit] += 1
                    counts["selected_unique_rows"] += 1
                    if split == "train":
                        train_episodes.add(episode)
                    else:
                        holdout_episodes.add(episode)
                        heldout_keys.add(key)
                        metrics.update(normalized, metric_model)
                        if rank <= 20:
                            hard_handle.write(serialized)
                            stats["hard_holdout"].update(normalized)
                            hard_episodes.add(episode)
                            hard_keys.add(key)
                            hard_metrics.update(normalized, metric_model)

                if counts["input_rows"] != expected_source_rows[date]:
                    raise ValueError(
                        f"{date} row count mismatch: {counts['input_rows']} != {expected_source_rows[date]}"
                    )

        overlap = train_episodes & holdout_episodes
        if overlap:
            raise ValueError(f"train/heldout episode overlap: {sorted(overlap)[:10]}")
        if not hard_keys <= heldout_keys:
            raise AssertionError("rank-1--20 hard holdout is not a subset of the Aug-6 holdout")
        if eligible_unique_by_unit != written_by_unit:
            raise AssertionError("whole episode-seat trajectories were not preserved")
        if not stats["train"].rows or not stats["holdout"].rows or not stats["hard_holdout"].rows:
            raise ValueError("temporal corpus or hard holdout is empty")

        for name, path in final_paths.items():
            temporary_paths[name].replace(path)
        anchor_temporary.replace(anchor_path)
        anchor["padded_path"] = _display(anchor_path)

        metric_payload = {
            "version": 1,
            "scope": "schema-3 zero-padded A2 NPZ ranker; single-action index agreement",
            "anchor": anchor,
            "heldout_aug6_rank1_100": metrics.finalize(ranks),
            "hard_aug6_rank1_20": hard_metrics.finalize(ranks),
        }
        metrics_temporary.write_text(
            json.dumps(metric_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        metrics_temporary.replace(metrics_path)

        output_report = {
            name: {
                "path": _display(path),
                "sha256": sha256_file(path),
                **stats[name].finalize(),
            }
            for name, path in final_paths.items()
        }
        observed_selected_teams = stats["train"].teams | stats["holdout"].teams
        manifest = {
            "version": 1,
            "kind": "deterministic_temporal_elite_schema3",
            "inputs": {
                "daily_schema3": source_reports,
                "frozen_aug4_team_ranking": {
                    "path": _display(ranking_path),
                    "sha256": sha256_file(ranking_path),
                    "teams": len(ranked_teams),
                },
                "exact_grim_deck": {
                    "path": _display(deck_path),
                    "sha256": sha256_file(deck_path),
                    "cards": len(exact_deck),
                    "canonical_sha256": expected_deck_digest,
                },
                "a2_anchor": anchor,
            },
            "rules": {
                "train_dates": sorted(TRAIN_DATES),
                "heldout_date": HOLDOUT_DATE,
                "winning_rows_only": True,
                "team_scope": "exact frozen Aug-4 ranks 1-100",
                "hard_holdout_scope": "Aug-6 winners from frozen Aug-4 ranks 1-20",
                "feature_schema": 3,
                "exact_deck_only": True,
                "deduplication_key": ["episode_id", "seat", "step"],
                "duplicate_policy": "skip byte-equivalent normalized rows; fail on conflicts",
                "split_unit": "source date, with whole eligible episode-seat trajectories retained",
                "raw_observation_removed": True,
                "a2_metric_denominator": "single-action decisions; meaningful top3 additionally requires >=4 options",
            },
            "known_candidate_lineage_exclusions": excluded_lineage,
            "audit": {
                "by_source_date": {date: dict(sorted(counts.items())) for date, counts in source_counts.items()},
                "selected_identical_duplicates_skipped": selected_duplicate_rows,
                "all_source_episodes": len(episode_dates),
                "all_source_episode_date_overlap": 0,
                "whole_episode_seat_trajectories_verified": True,
                "hard_holdout_is_subset": True,
                "observed_selected_teams": [
                    {"rank": ranks[team], "team": team}
                    for team in sorted(observed_selected_teams, key=lambda value: ranks[value])
                ],
            },
            "leakage": {
                "train_episode_count": len(train_episodes),
                "train_episode_ids_sha256": _digest_strings(train_episodes),
                "train_episode_ids": sorted(train_episodes),
                "heldout_episode_count": len(holdout_episodes),
                "heldout_episode_ids_sha256": _digest_strings(holdout_episodes),
                "heldout_episode_ids": sorted(holdout_episodes),
                "train_heldout_episode_overlap": [],
                "hard_holdout_episode_count": len(hard_episodes),
                "hard_holdout_episode_ids_sha256": _digest_strings(hard_episodes),
            },
            "outputs": {
                **output_report,
                "a2_schema3_anchor": {
                    "path": _display(anchor_path),
                    "sha256": sha256_file(anchor_path),
                },
                "a2_metrics": {
                    "path": _display(metrics_path),
                    "sha256": sha256_file(metrics_path),
                },
            },
            "a2_headline": {
                "heldout_aug6_rank1_100": metric_payload["heldout_aug6_rank1_100"]["overall"],
                "hard_aug6_rank1_20": metric_payload["hard_aug6_rank1_20"]["overall"],
            },
        }
        manifest_temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        manifest_temporary.replace(manifest_path)
        return manifest
    except Exception:
        for path in cleanup:
            if path.exists():
                path.unlink()
        raise


def _default_sources(source_root: Path) -> dict[str, tuple[Path, Path]]:
    return {
        date: (source_root / "shards" / f"{date}.jsonl.gz", source_root / "manifests" / f"{date}.json")
        for date in DATES
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT / "data" / "grim_daily_v3")
    parser.add_argument("--team-ranking", type=Path, default=ROOT / "data" / "top_teams_20260804.txt")
    parser.add_argument("--deck", type=Path, default=ROOT / "freshstart" / "decklists" / "grimmsnarl_marnie.deck.csv")
    parser.add_argument("--a2", type=Path, default=ROOT / "artifacts" / "recovery_probes" / "extracted" / "a2" / "policy_weights.npz")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "emergency_strength_sprint" / "temporal_elite_schema3")
    parser.add_argument("--exclude-team", action="append", default=[])
    args = parser.parse_args()

    exclusions = discover_local_lineage(ROOT)
    for team in args.exclude_team:
        exclusions.setdefault(team, {"basis": "explicit --exclude-team argument"})
    manifest = build_temporal_elite_schema3(
        sources=_default_sources(args.source_root),
        ranking_path=args.team_ranking,
        deck_path=args.deck,
        a2_path=args.a2,
        output_dir=args.output_dir,
        excluded_lineage=exclusions,
    )
    print(json.dumps({
        "manifest": _display(args.output_dir / "manifest.json"),
        "outputs": manifest["outputs"],
        "a2_headline": manifest["a2_headline"],
        "known_candidate_lineage_exclusions": sorted(exclusions),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
